# -*- coding: utf-8 -*-
"""Pure element-transform computation for the am-safe-change skill.

Runs under IronPython 2.7 (inside Revit) and CPython 3 (tests). No f-strings,
no type annotations, no nonlocal. No Revit imports: this module never touches
the model.

Request contract (what the am-bim-viewer "Copy changes for Revit" button makes):
    {"kind": "element-transforms", "source": "am-bim-viewer", "units": "ft",
     "items": [{"id": 123, "name": "...", "category": "...",
                "move": [dx, dy, dz], "rotateZ": 15.0, "pivot": [x, y, z]}]}
All lengths are Revit internal units (decimal feet). rotateZ is in degrees,
counter-clockwise positive in plan, about a vertical axis through pivot.

ORDER OF OPERATIONS (lib, apply script and recipe all use this order):
    1. rotate by rotateZ about the vertical axis through pivot
       (pivot is in the coordinates BEFORE the move), then
    2. move by [dx, dy, dz].
    after = R(before - pivot) + pivot + move

Element read shape (what read_elements.py returns per id):
    {"id", "exists", "name", "category", "kind": "point"|"curve"|"none",
     "point": [x, y, z] (location point, or curve midpoint), "rotation": deg|None,
     "pinned", "groupId" (0 = none), "hostId" (0 = none or a Level),
     "hostCategory", "dependents": [ids of family instances hosted by it],
     "isView", "viewSpecific"}
"""
import math
import re

KIND = "element-transforms"
COLUMNS = ["ElementId", "Name", "Category", "Location", "Rotation"]
CHANGED = ["Location", "Rotation"]
POINT_TOL = 1e-6   # ft, stale-state guard and compare
ANGLE_TOL = 1e-4   # deg, compare

# Warning types. SKIP_ONLY can only be cleared by removing the id from scope.
# ACCEPTABLE can be cleared by removing the id, or by the user accepting it.
SKIP_ONLY = ("not_found", "pinned", "grouped", "not_movable", "non_vertical_axis")
ACCEPTABLE = ("hosted", "hosts_others")

_UNIT_HINTS = [
    ("feetFractionalInches", "feet and fractional inches", None, None),
    ("fractionalInches", "fractional inches", None, None),
    ("feet", "decimal feet", None, None),
    ("inches", "decimal inches", None, None),
    ("millimeters", "millimeters", 304.8, "mm"),
    ("centimeters", "centimeters", 30.48, "cm"),
    ("meters", "meters", 0.3048, "m"),
]


# ---------------------------------------------------------------- validation

def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _vec3(v):
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(_is_num(x) for x in v)


def validate_request(req):
    """Return (items, errors). items are normalised dicts; errors are strings.

    Any error means the request is rejected before the model is read.
    """
    errors = []
    if not isinstance(req, dict):
        return [], ["The request is not a JSON object."]
    if req.get("kind") != KIND:
        errors.append("kind must be '%s', got %r." % (KIND, req.get("kind")))
    if req.get("units") != "ft":
        errors.append("units must be 'ft' (Revit internal units), got %r." % (req.get("units"),))
    raw = req.get("items")
    if not isinstance(raw, list) or not raw:
        errors.append("items must be a non-empty list.")
        return [], errors
    items = []
    seen = set()
    for i, it in enumerate(raw):
        where = "items[%d]" % i
        if not isinstance(it, dict):
            errors.append("%s is not an object." % where)
            continue
        eid = it.get("id")
        if not isinstance(eid, int) or isinstance(eid, bool) or eid <= 0:
            errors.append("%s: id must be a positive integer element id." % where)
            continue
        where = "items[%d] (id %d)" % (i, eid)
        if eid in seen:
            errors.append("%s: the id is listed twice." % where)
            continue
        seen.add(eid)
        if "move" not in it:
            errors.append("%s: move is missing." % where)
            continue
        if not _vec3(it["move"]):
            errors.append("%s: move must be [dx, dy, dz] numbers." % where)
            continue
        if "rotateZ" not in it:
            errors.append("%s: rotateZ is missing." % where)
            continue
        if not _is_num(it["rotateZ"]):
            errors.append("%s: rotateZ must be a number of degrees." % where)
            continue
        rz = float(it["rotateZ"])
        pivot = it.get("pivot")
        if pivot is not None and not _vec3(pivot):
            errors.append("%s: pivot must be [x, y, z] numbers." % where)
            continue
        if rz != 0 and pivot is None:
            errors.append("%s: pivot is missing (needed when rotateZ is not 0)." % where)
            continue
        other_axes = []
        for k in ("rotateX", "rotateY"):
            if _is_num(it.get(k)) and float(it[k]) != 0:
                other_axes.append(k)
        items.append({
            "id": eid,
            "name": it.get("name") or "",
            "category": it.get("category") or "",
            "move": [float(x) for x in it["move"]],
            "rotateZ": rz,
            "pivot": [float(x) for x in pivot] if pivot is not None else None,
            "otherAxes": other_axes,
        })
    return items, errors


# ---------------------------------------------------------------- math

def cos_sin(deg):
    """cos and sin of deg. Exact for multiples of 90 degrees."""
    q = deg % 360.0
    exact = {0.0: (1.0, 0.0), 90.0: (0.0, 1.0), 180.0: (-1.0, 0.0), 270.0: (0.0, -1.0)}
    if q in exact:
        return exact[q]
    r = math.radians(deg)
    return math.cos(r), math.sin(r)


def rotate_xy(point, pivot, deg):
    """Rotate point about the vertical axis through pivot, CCW positive."""
    c, s = cos_sin(deg)
    x = point[0] - pivot[0]
    y = point[1] - pivot[1]
    return [pivot[0] + c * x - s * y, pivot[1] + s * x + c * y, point[2]]


def norm_deg(deg):
    """Angle in [0, 360)."""
    d = deg % 360.0
    if d >= 360.0 - 1e-12 or abs(d) < 1e-12:
        return 0.0
    return d


def angle_diff(a, b):
    """Smallest absolute difference of two angles in degrees (mod 360)."""
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def after_state(point, rotation, move, rotate_z, pivot):
    """Return (point_after, rotation_after). Rotate about pivot, then move."""
    p = list(point)
    if rotate_z:
        p = rotate_xy(p, pivot, rotate_z)
    p = [p[0] + move[0], p[1] + move[1], p[2] + move[2]]
    r = None if rotation is None else norm_deg(rotation + rotate_z)
    return p, r


def points_close(a, b, tol=POINT_TOL):
    return all(abs(a[i] - b[i]) <= tol for i in range(3))


# ---------------------------------------------------------------- read result

_ESC_RE = re.compile(r"\\(\\|u[0-9a-fA-F]{4})")


def unescape(text):
    """Reverse the IronPython ASCII escaping done by the read/apply scripts."""
    def rep(m):
        tok = m.group(1)
        if tok == "\\":
            return "\\"
        try:
            return unichr(int(tok[1:], 16))  # noqa: F821 (IronPython / Py2)
        except NameError:
            return chr(int(tok[1:], 16))
    return _ESC_RE.sub(rep, text or "")


def load_read_result(result):
    """Turn a read_elements.py result (or the full run JSON) into (elements, units)."""
    if "result" in result and "elements" not in result:
        result = result["result"]
    if result is None:
        raise ValueError("The run has no result (check status and error).")
    out = []
    for e in result["elements"]:
        d = dict(e)
        if result.get("escaped"):
            d["name"] = unescape(d.get("name"))
            d["category"] = unescape(d.get("category"))
            d["hostCategory"] = unescape(d.get("hostCategory"))
        out.append(d)
    return out, result.get("lengthUnit") or ""


def unit_hint(type_id):
    """(label, factor, symbol) for a Revit length unit type id, e.g.
    'autodesk.unit.unit:millimeters-1.0.1' -> ('millimeters', 304.8, 'mm')."""
    tid = (type_id or "").split(":")[-1].split("-")[0]
    for key, label, factor, sym in _UNIT_HINTS:
        if tid == key:
            return label, factor, sym
    return (tid or "unknown"), None, None


# ---------------------------------------------------------------- formatting

def _f(v):
    s = "%.3f" % v
    return "0.000" if s == "-0.000" else s


def fmt_point(p, unit_type=None):
    if p is None:
        return "-"
    text = "(%s, %s, %s) ft" % (_f(p[0]), _f(p[1]), _f(p[2]))
    _label, factor, sym = unit_hint(unit_type)
    if factor:
        dec = 0 if sym == "mm" else (1 if sym == "cm" else 3)
        fmt = "%." + str(dec) + "f"
        text += " = (%s) %s" % (", ".join(fmt % (c * factor) for c in p), sym)
    return text


def fmt_rot(r):
    if r is None:
        return "-"
    return "%s deg" % ("%.2f" % r)


# ---------------------------------------------------------------- preview

def _warn(rows, eid, wtype, text, blocking):
    rows.append({"row": str(eid), "type": wtype, "text": text, "blocking": blocking})


def compute_preview(request, elements, unit_type="", skip_ids=None, accept=None, title=None):
    """Build the change-preview (shared contract) for a validated request.

    request  : the raw request dict (validated here; errors raise ValueError)
    elements : read_elements.py element dicts
    skip_ids : ids the user removed from scope (they stay in the table, unchanged)
    accept   : warning types from ACCEPTABLE that the user accepted
    """
    items, errors = validate_request(request)
    if errors:
        raise ValueError("Request rejected: " + " ".join(errors))
    skip = set(skip_ids or [])
    accepted = set(accept or [])
    bad = sorted(a for a in accepted if a not in ACCEPTABLE)
    if bad:
        raise ValueError("These warning types cannot be accepted, only skipped: %s" % ", ".join(bad))
    by_id = dict((e["id"], e) for e in elements)

    warnings = []
    before, after, steps = [], [], []
    moved = 0
    for it in items:
        eid = it["id"]
        el = by_id.get(eid)
        if el is None or not el.get("exists"):
            name = it["name"]
            cat = it["category"]
            before.append([eid, name, cat, "-", "-"])
            after.append([eid, name, cat, "-", "-"])
            if eid not in skip:
                _warn(warnings, eid, "not_found", "Element %d is not in the model (deleted, or a different model)." % eid, True)
            continue
        name = el.get("name") or it["name"]
        cat = el.get("category") or it["category"]
        p0 = el.get("point")
        r0 = el.get("rotation")
        row_before = [eid, name, cat, fmt_point(p0, unit_type), fmt_rot(r0)]
        before.append(row_before)
        if eid in skip:
            after.append(list(row_before))
            continue

        row_w = []
        if el.get("isView") or el.get("kind") not in ("point", "curve") or p0 is None:
            _warn(row_w, eid, "not_movable", "%s '%s' has no point or line location. This recipe cannot move it." % (cat, name), True)
        if el.get("pinned"):
            _warn(row_w, eid, "pinned", "%s '%s' is pinned. Revit does not move pinned elements." % (cat, name), True)
        if el.get("groupId"):
            _warn(row_w, eid, "grouped", "%s '%s' is in group %s. Move the whole group, or skip it." % (cat, name, el["groupId"]), True)
        if el.get("hostId"):
            _warn(row_w, eid, "hosted", "%s '%s' is hosted by %s %s. It can only move along its host." % (
                cat, name, el.get("hostCategory") or "element", el["hostId"]), "hosted" not in accepted)
        deps = el.get("dependents") or []
        if deps:
            _warn(row_w, eid, "hosts_others", "%s '%s' hosts %d element(s) (for example doors or windows). They move with it." % (
                cat, name, len(deps)), "hosts_others" not in accepted)
        if it["otherAxes"]:
            _warn(row_w, eid, "non_vertical_axis", "Rotation about %s is not supported. Only rotateZ (plan rotation) is." % " and ".join(it["otherAxes"]), True)
        if it["move"][2] != 0:
            _warn(row_w, eid, "cross_level", "dz = %s ft. The element keeps its level. Its offset from the level changes." % _f(it["move"][2]), False)
        if it["rotateZ"] != 0 and r0 is None and el.get("kind") == "point":
            _warn(row_w, eid, "rotation_unknown", "Revit does not report a rotation for %s '%s'. The location still rotates about the pivot." % (cat, name), False)
        if el.get("viewSpecific"):
            _warn(row_w, eid, "view_specific", "%s '%s' is drawn in one view only." % (cat, name), False)
        warnings.extend(row_w)

        if p0 is None:
            after.append(list(row_before))
            continue
        p1, r1 = after_state(p0, r0, it["move"], it["rotateZ"], it["pivot"])
        after.append([eid, name, cat, fmt_point(p1, unit_type), fmt_rot(r1)])
        if it["move"] == [0.0, 0.0, 0.0] and it["rotateZ"] == 0:
            continue
        moved += 1
        steps.append({"id": eid, "move": it["move"], "rotateZ": it["rotateZ"],
                      "pivot": it["pivot"], "kind": el.get("kind"),
                      "expect": {"point": list(p0), "rotation": r0},
                      "expectAfter": {"point": p1, "rotation": r1}})

    blocked = any(w["blocking"] for w in warnings)
    label, _f2, _s = unit_hint(unit_type)
    notes = [
        "%d of %d elements move or rotate." % (moved, len(items)),
        "Lengths are Revit internal feet. The project shows lengths in %s." % label,
        "Order: rotate about the pivot first (vertical axis, counter-clockwise positive), then move.",
        "Location is the location point, or the midpoint of the location line.",
    ]
    if skip:
        notes.append("Skipped by the user (no change): %s." % ", ".join(str(i) for i in sorted(skip)))
    if accepted:
        notes.append("Accepted by the user: %s." % ", ".join(sorted(accepted)))
    if blocked:
        notes.append("BLOCKED: decide every blocking warning before apply.")
    return {
        "kind": "change-preview",
        "title": title or ("Move or rotate %d element(s)" % moved),
        "keyColumn": "ElementId",
        "columns": list(COLUMNS),
        "changedColumns": list(CHANGED),
        "before": before,
        "after": after,
        "notes": notes,
        "warnings": warnings,
        "blocked": blocked,
        "params": {"source": request.get("source") or "", "units": "ft",
                   "skip": sorted(skip), "accept": sorted(accepted),
                   "lengthUnit": unit_type or ""},
        "steps": [] if blocked else steps,
    }


def decisions_needed(preview):
    """Group blocking warnings by type: {type: [row ids]} (one question per type)."""
    out = {}
    for w in preview["warnings"]:
        if w.get("blocking"):
            out.setdefault(w["type"], []).append(w["row"])
    return out


# ---------------------------------------------------------------- compare

def compare(preview, actual):
    """Compare preview steps' expectAfter with actual results.

    actual: {id: {"point": [x,y,z], "rotation": deg|None}} for every moved element.
    Returns a list of difference strings. Empty list = matches preview.
    """
    diffs = []
    for st in preview.get("steps") or []:
        eid = st["id"]
        got = actual.get(eid)
        want = st["expectAfter"]
        if got is None:
            diffs.append("element %s: missing in actual result" % eid)
            continue
        if got.get("point") is None or not points_close(got["point"], want["point"]):
            diffs.append("element %s: location expected %s, got %s" % (
                eid, fmt_point(want["point"]), fmt_point(got.get("point"))))
        wr, gr = want.get("rotation"), got.get("rotation")
        if wr is not None:
            if gr is None or angle_diff(wr, gr) > ANGLE_TOL:
                diffs.append("element %s: rotation expected %s, got %s" % (eid, fmt_rot(wr), fmt_rot(gr)))
    want_ids = set(st["id"] for st in preview.get("steps") or [])
    for eid in sorted(actual):
        if eid not in want_ids:
            diffs.append("element %s: changed but not in preview" % eid)
    return diffs


def actual_from(data):
    """{id: {point, rotation}} from an apply result or a read_elements result."""
    if "result" in data and "elements" not in data and "rows" not in data:
        data = data["result"]
    if data is None:
        raise ValueError("The run has no result (check status and error).")
    if "rows" in data:
        return dict((r["id"], {"point": r.get("point"), "rotation": r.get("rotation")}) for r in data["rows"])
    els, _u = load_read_result(data)
    return dict((e["id"], {"point": e.get("point"), "rotation": e.get("rotation")}) for e in els if e.get("exists"))


def text_table(preview):
    """Compact markdown table for chat."""
    out = ["| ElementId | Name | Category | Location before -> after | Rotation before -> after |",
           "|---|---|---|---|---|"]
    for b, a in zip(preview["before"], preview["after"]):
        out.append("| %s | %s | %s | %s -> %s | %s -> %s |" % (b[0], b[1], b[2], b[3], a[3], b[4], a[4]))
    out.append("")
    nb = sum(1 for w in preview["warnings"] if w.get("blocking"))
    out.append("Steps: %d. Warnings: %d (blocking: %d)." % (len(preview["steps"]), len(preview["warnings"]), nb))
    for w in preview["warnings"]:
        out.append("- %s[%s] %s" % ("BLOCKING " if w.get("blocking") else "", w["type"], w["text"]))
    return "\n".join(out)

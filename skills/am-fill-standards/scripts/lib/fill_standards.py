# -*- coding: utf-8 -*-
"""Pure fill-standards computation for the am-fill-standards skill.

Runs under IronPython 2.7 (inside Revit) and CPython 3 (tests,
fill_report.py). No f-strings, no type annotations, no nonlocal. No Revit
imports: this module never touches the model. It only turns a
read_fills.py read result into name checks, a rename table, a reference
view sync plan, and a report.

Read result shape (what read_fills.py returns):
    {"model", "revit_year", "timestamp", "path",
     "reference_view": {"id", "name", "type"} or None,
     "drafting_views": [{"id", "name", "type", "region_count"}],
     "types": [{"id", "name", "masking": bool or None,
                "fg": {"pattern", "pattern_id", "color": {"r","g","b"} or None},
                "bg": {"pattern", "pattern_id", "color"},
                "line_weight": int or None,
                "drawing_uses": int, "reference_uses": int}],
     "patterns": [{"id", "name", "target": "Drafting" or "Model" or None}],
     "swatches": [{"id", "type_id", "type_name", "cx", "cy"}],
     "labels": [{"id", "text", "cx", "cy", "text_type_id"}]}

A swatch is a FilledRegion instance in the reference view. A label is a
TextNote in the same view. Centers (cx, cy) are in feet, in view
coordinates. A center is None when Revit gave no bounding box: that
swatch or label cannot be paired, and the plan says so.
"""
import math
import re

# Office convention from the issue: a type name that carries _OPQ has
# Masking on, a name that carries _TRN has Masking off. The rule is
# configurable: pass other tokens through the rules dict.
OPQ_SUFFIX = "_OPQ"
TRN_SUFFIX = "_TRN"

# Pairing guard from the issue: a label pairs with its nearest swatch
# only when the next nearest swatch is much farther away. "Much
# farther" is this ratio: second distance must be above guard * first.
PAIR_GUARD_RATIO = 1.5

_TRAILING_NUMBER_RE = re.compile(r"[ _]\d+$")
_ESC_RE = re.compile(r"\\(\\|u[0-9a-fA-F]{4})")


def suffix_status(name, masking, opq=OPQ_SUFFIX, trn=TRN_SUFFIX):
    """Name suffix against Masking: "mismatch", "ok", "unverified", None.

    None means the name carries neither suffix, so the rule does not
    apply. "unverified" means the name carries a suffix but Masking
    could not be read (masking is None): the check cannot judge it,
    and must not call it a mismatch.
    """
    has_opq = opq in name
    has_trn = trn in name
    if not has_opq and not has_trn:
        return None
    if masking is None:
        return "unverified"
    if has_opq and not masking:
        return "mismatch"
    if has_trn and masking:
        return "mismatch"
    return "ok"


def typo_flags(name):
    """Typo flags for one type name, in first-seen order."""
    flags = []
    if name != name.strip():
        flags.append("leading/trailing space")
    if "  " in name:
        flags.append("double space")
    if "__" in name:
        flags.append("double underscore")
    if _TRAILING_NUMBER_RE.search(name):
        flags.append("trailing number")
    return flags


def check_type(name, masking, opq=OPQ_SUFFIX, trn=TRN_SUFFIX):
    """All name flags for one type: suffix status plus typo flags."""
    flags = []
    status = suffix_status(name, masking, opq, trn)
    if status == "mismatch":
        if opq in name and not masking:
            flags.append("OPQ name but Masking off")
        elif trn in name and masking:
            flags.append("TRN name but Masking on")
    elif status == "unverified":
        flags.append("suffix present but Masking unknown")
    flags.extend(typo_flags(name))
    return flags


def split_label(name):
    """Type name -> (line 1, line 2) for a reference view label.

    Line 1 is the prefix: the text before the first "-" or "_", after
    leading separators are stripped. Line 2 is the rest. A name with no
    separator stays on one line. Long names split this way do not run
    into the next column.
    """
    stripped = name.lstrip("-_")
    for i, ch in enumerate(stripped):
        if ch in "-_":
            return stripped[:i], stripped[i + 1:]
    return stripped, ""


def label_text(name):
    """The two-line label text for a type name (one line when no split)."""
    line1, line2 = split_label(name)
    if line2:
        return line1 + "\n" + line2
    return line1


def _distance(a, b):
    """Euclidean distance between two (cx, cy) centers, in feet."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def pair_labels(labels, swatches, guard=PAIR_GUARD_RATIO):
    """Pair each label with its nearest swatch, guarded.

    Returns (pairs, unpaired). pairs maps label id -> swatch id or None.
    A label pairs only when it has a center, at least one swatch has a
    center, and the second nearest swatch is farther than guard * the
    nearest distance. Otherwise the label stays unpaired for the user
    to resolve by hand: the guard is the point of the pairing, not a
    detail to work around.
    """
    placed = [s for s in swatches if s.get("cx") is not None
              and s.get("cy") is not None]
    pairs = {}
    unpaired = []
    for label in labels:
        lid = label["id"]
        if label.get("cx") is None or label.get("cy") is None:
            pairs[lid] = None
            unpaired.append(lid)
            continue
        if not placed:
            pairs[lid] = None
            unpaired.append(lid)
            continue
        ranked = sorted(
            placed,
            key=lambda s: _distance((label["cx"], label["cy"]),
                                    (s["cx"], s["cy"])))
        nearest = ranked[0]
        if len(ranked) == 1:
            pairs[lid] = nearest["id"]
            continue
        d1 = _distance((label["cx"], label["cy"]),
                       (nearest["cx"], nearest["cy"]))
        d2 = _distance((label["cx"], label["cy"]),
                       (ranked[1]["cx"], ranked[1]["cy"]))
        if d1 == 0 or d2 > guard * d1:
            pairs[lid] = nearest["id"]
        else:
            pairs[lid] = None
            unpaired.append(lid)
    return pairs, unpaired


def classify_use(drawing_uses, reference_uses):
    """"drawings", "reference only", or "unused", from the use split."""
    if drawing_uses > 0:
        return "drawings"
    if reference_uses > 0:
        return "reference only"
    return "unused"


def build_rename_table(rows, mapping):
    """Build an approved rename table from a user mapping.

    rows: [{"id", "name"}]. mapping: {old name: new name}, supplied
    and approved by the user. Never rename without this table.
    Returns (table, errors). table has {"id", "old", "new"} for rows
    whose new name differs. errors lists every rejected mapping:
    unknown old name, empty new name, two old names mapping to one
    new name, or a new name that collides with a type that is not
    itself renamed away. A row with new == old is dropped, not an
    error: the user looked at it and kept it.
    """
    by_name = {}
    for row in rows:
        by_name[row["name"]] = row
    renamed_away = set(mapping.keys())
    table = []
    errors = []
    seen_new = {}
    for old, new in mapping.items():
        if old not in by_name:
            errors.append("unknown type: %r" % old)
            continue
        if not new or not new.strip():
            errors.append("empty new name for %r" % old)
            continue
        if new == old:
            continue
        if new in seen_new:
            errors.append("two types map to %r: %r and %r" % (
                new, seen_new[new], old))
            continue
        if new in by_name and new not in renamed_away:
            errors.append("new name %r collides with existing type" % new)
            continue
        seen_new[new] = old
        table.append({"id": by_name[old]["id"], "old": old, "new": new})
    return table, errors


def pattern_usage(patterns, types):
    """Fill pattern id -> {"fg": [type names], "bg": [type names]}.

    Only filled region types count here. Materials also use fill
    patterns, but that is am-material-audit territory, not this
    report: the usage lists say so when they are empty.
    """
    usage = {}
    for p in patterns:
        usage[p["id"]] = {"fg": [], "bg": []}
    for t in types:
        for slot in ("fg", "bg"):
            entry = t.get(slot) or {}
            pid = entry.get("pattern_id")
            if pid in usage:
                usage[pid][slot].append(t["name"])
    return usage


def unescape(text):
    """Reverse backslash-uXXXX escaping (the material_audit method).

    The read script's jsonable step is the primary path for non-ASCII
    names (a degree sign in a pattern name survives it). This helper
    covers hand-made read results where a name arrives with literal
    backslash escapes instead.
    """
    def rep(m):
        tok = m.group(1)
        if tok == "\\":
            return "\\"
        try:
            return unichr(int(tok[1:], 16))  # noqa: F821 (IronPython / Py2)
        except NameError:
            return chr(int(tok[1:], 16))
    return _ESC_RE.sub(rep, text)


def load_read_result(result):
    """Unwrap a run JSON and unescape literal backslash escapes."""
    if "result" in result and "types" not in result:
        result = result["result"]
    for key in ("types", "patterns", "swatches", "labels"):
        for row in result.get(key) or []:
            for field in ("name", "type_name", "text"):
                value = row.get(field)
                if isinstance(value, str) and "\\u" in value:
                    row[field] = unescape(value)
    return result


def _label_lines(text):
    """Label text as stripped lines, blank lines dropped.

    Two labels match only when their line lists match: a one-line
    "HATCH A" is not the two-line label "HATCH" / "A", because the
    two-line form is what keeps long names out of the next column.
    """
    return [ln.strip() for ln in (text or "").split("\n")
            if ln.strip()]


def sync_plan(types, swatches, labels, pairs):
    """Reference view sync plan from a read result.

    Returns {"missing", "stale", "label_fixes", "unpaired_labels"}:
    - missing: types used in drawings with no swatch in the view.
    - stale: swatches whose type is used in no drawing. Flagged only,
      never deleted by the sync: the user decides what to remove.
    - label_fixes: paired labels whose text is not the swatch type's
      two-line label, with the expected text.
    - unpaired_labels: labels the guard refused to pair.
    """
    swatch_by_type = {}
    for s in swatches:
        swatch_by_type[s["type_id"]] = s
    type_by_id = {}
    for t in types:
        type_by_id[t["id"]] = t
    missing = []
    for t in types:
        if t.get("drawing_uses", 0) > 0 and t["id"] not in swatch_by_type:
            missing.append({"id": t["id"], "name": t["name"],
                            "drawing_uses": t["drawing_uses"]})
    stale = []
    for s in swatches:
        t = type_by_id.get(s["type_id"])
        drawing = 0 if t is None else t.get("drawing_uses", 0)
        if drawing == 0:
            stale.append({"id": s["id"], "type_id": s["type_id"],
                          "type_name": s.get("type_name")})
    swatch_by_id = {}
    for s in swatches:
        swatch_by_id[s["id"]] = s
    label_by_id = {}
    for label in labels:
        label_by_id[label["id"]] = label
    label_fixes = []
    unpaired_labels = []
    for label_id, swatch_id in pairs.items():
        if swatch_id is None:
            unpaired_labels.append(label_id)
            continue
        swatch = swatch_by_id.get(swatch_id)
        label = label_by_id.get(label_id)
        if swatch is None or label is None:
            unpaired_labels.append(label_id)
            continue
        t = type_by_id.get(swatch["type_id"])
        if t is None:
            unpaired_labels.append(label_id)
            continue
        expected = label_text(t["name"])
        if _label_lines(label.get("text")) != _label_lines(expected):
            label_fixes.append({"label_id": label_id,
                                "swatch_id": swatch_id,
                                "type_id": t["id"],
                                "type_name": t["name"],
                                "current": label.get("text"),
                                "expected": expected})
    return {"missing": missing, "stale": stale,
            "label_fixes": label_fixes, "unpaired_labels": unpaired_labels}


def report(read_result, rules=None):
    """Build the fill-standards report from a read_fills.py result.

    Returns {"model", "revit_year", "timestamp", "reference_view",
    "rows", "patterns", "reference", "counts"}. Each row has "id",
    "name", "masking", "fg" / "bg" (pattern, pattern_id, color text),
    "line_weight", "drawing_uses", "reference_uses", "used"
    ("drawings", "reference only", or "unused") and "flags" (suffix
    mismatch plus typo flags). rules overrides the OPQ/TRN tokens.
    """
    result = load_read_result(read_result)
    rules = rules or {}
    opq = rules.get("opq", OPQ_SUFFIX)
    trn = rules.get("trn", TRN_SUFFIX)
    rows = []
    for t in result.get("types") or []:
        def entry_text(entry):
            entry = entry or {}
            color = entry.get("color")
            if color is None:
                color_text = "-"
            else:
                color_text = "%d, %d, %d" % (int(color["r"]),
                                             int(color["g"]),
                                             int(color["b"]))
            return {"pattern": entry.get("pattern") or "<none>",
                    "pattern_id": entry.get("pattern_id"),
                    "color": color_text}
        rows.append({
            "id": t["id"],
            "name": t["name"],
            "masking": t.get("masking"),
            "fg": entry_text(t.get("fg")),
            "bg": entry_text(t.get("bg")),
            "line_weight": t.get("line_weight"),
            "drawing_uses": t.get("drawing_uses", 0),
            "reference_uses": t.get("reference_uses", 0),
            "used": classify_use(t.get("drawing_uses", 0),
                                 t.get("reference_uses", 0)),
            "flags": check_type(t["name"], t.get("masking"), opq, trn),
        })
    usage = pattern_usage(result.get("patterns") or [],
                          result.get("types") or [])
    patterns = []
    for p in result.get("patterns") or []:
        use = usage.get(p["id"]) or {"fg": [], "bg": []}
        patterns.append({"id": p["id"], "name": p["name"],
                         "target": p.get("target"),
                         "fg_types": use["fg"], "bg_types": use["bg"]})
    pairs, unpaired = pair_labels(result.get("labels") or [],
                                  result.get("swatches") or [])
    plan = sync_plan(result.get("types") or [],
                     result.get("swatches") or [],
                     result.get("labels") or [], pairs)
    flagged = [r for r in rows if r["flags"]]
    return {
        "model": result.get("model", ""),
        "revit_year": result.get("revit_year", ""),
        "timestamp": result.get("timestamp", ""),
        "reference_view": result.get("reference_view"),
        "rows": rows,
        "patterns": patterns,
        "reference": {"swatches": len(result.get("swatches") or []),
                      "labels": len(result.get("labels") or []),
                      "pairs": pairs,
                      "unpaired_labels": unpaired,
                      "missing": plan["missing"],
                      "stale": plan["stale"],
                      "label_fixes": plan["label_fixes"]},
        "counts": {"types": len(rows),
                   "drawings": len([r for r in rows
                                    if r["used"] == "drawings"]),
                   "reference_only": len([r for r in rows
                                          if r["used"] == "reference only"]),
                   "unused": len([r for r in rows
                                  if r["used"] == "unused"]),
                   "flagged": len(flagged),
                   "patterns": len(patterns)},
    }


def _cell(text, width):
    """Pad or cut a table cell to width. Text is ASCII on purpose."""
    text = "" if text is None else str(text)
    if len(text) > width:
        text = text[:width - 1] + "~"
    return text + " " * (width - len(text))


def render_table(rep):
    """Plain-text report table plus summary, for the terminal and chat."""
    rows = rep["rows"]
    lines = []
    lines.append("Filled region types: %d total, %d in drawings, "
                 "%d reference only, %d unused, %d flagged" % (
                     rep["counts"]["types"], rep["counts"]["drawings"],
                     rep["counts"]["reference_only"],
                     rep["counts"]["unused"], rep["counts"]["flagged"]))
    if not rows:
        lines.append("No filled region types in this model.")
        return "\n".join(lines)
    widths = (30, 7, 24, 24, 8, 8, 14, 30)
    header = [_cell(t, w) for t, w in zip(
        ["Type", "Masking", "Foreground pattern / RGB",
         "Background pattern / RGB", "Draw", "Ref", "Used", "Flags"],
        widths)]
    lines.append(" | ".join(header))
    lines.append("-+-".join(["-" * w for w in widths]))
    for r in rows:
        def pat(entry):
            return "%s (%s)" % (entry["pattern"], entry["color"])
        masking = "-" if r["masking"] is None else (
            "on" if r["masking"] else "off")
        cells = [_cell(r["name"], widths[0]),
                 _cell(masking, widths[1]),
                 _cell(pat(r["fg"]), widths[2]),
                 _cell(pat(r["bg"]), widths[3]),
                 _cell(r["drawing_uses"], widths[4]),
                 _cell(r["reference_uses"], widths[5]),
                 _cell(r["used"], widths[6]),
                 _cell(", ".join(r["flags"]), widths[7])]
        lines.append(" | ".join(cells))
    lines.append("")
    ref = rep["reference"]
    if ref["missing"]:
        lines.append("Types in drawings with no swatch: %s" % ", ".join(
            m["name"] for m in ref["missing"]))
    if ref["stale"]:
        lines.append("Swatches with no drawing use (flagged, not removed): %s"
                     % ", ".join(s["type_name"] or "?" for s in ref["stale"]))
    if ref["label_fixes"]:
        lines.append("Labels to rewrite: %d" % len(ref["label_fixes"]))
        for fix in ref["label_fixes"]:
            lines.append("  %s -> %r" % (fix["type_name"],
                                         fix["expected"]))
    if ref["unpaired_labels"]:
        lines.append("Labels the guard refused to pair (resolve by hand): %s"
                     % ", ".join(str(i) for i in ref["unpaired_labels"]))
    return "\n".join(lines)

# -*- coding: utf-8 -*-
"""Plan 2D annotation in a detail view, and draw it as a preview (issue #298).

A field session finished an empty floor transition detail: 3 filled
regions, 10 detail lines and 3 text notes with leaders, in the style of
finished details on another sheet. The user approved only after a
drawing preview (SVG over a capture of the view), not after a table.

This module:
- reads the result of scripts/read_detail_annotation.py,
- sums up the house style of the reference details (types, line
  styles, leader layout),
- copies linework from a reference detail by translation,
- turns a plan (items in view coordinates) into an am-safe-change
  change preview with ordered steps,
- maps view coordinates to the pixels of a view capture, and draws the
  plan as SVG over the capture (an HTML page),
- compares an apply result with the preview.

View coordinates: u to the right and v up, in feet, measured in the view
plane from View.Origin along View.RightDirection and View.UpDirection.
A model point is origin + right * u + up * v. So every planned point
lies in the view plane.

Pure computation. Runs under CPython 3 and IronPython 2.7: no f-strings,
no type annotations, no nonlocal. No Revit imports.
"""
import base64
import struct

READ_KIND = "detail-annotation-read"

FILLED_REGION = "filled_region"
DETAIL_LINE = "detail_line"
TEXT_NOTE = "text_note"
KINDS = (FILLED_REGION, DETAIL_LINE, TEXT_NOTE)
KIND_LABELS = {FILLED_REGION: "Filled region", DETAIL_LINE: "Detail line",
               TEXT_NOTE: "Text note"}

# Categories of the elements the apply script creates on purpose.
EDITED_CATEGORIES = {FILLED_REGION: "Detail Items", DETAIL_LINE: "Lines",
                     TEXT_NOTE: "Text Notes"}

# FilledRegion.Create adds its own sketch: sketch lines, automatic sketch
# dimensions, and a sketch and sketch plane with no category. The field
# dry run of 3 filled regions added 18 + 14 + 6 such elements. They are
# expected, not a side effect to stop for.
FILLED_REGION_SIDE_EFFECTS = ["<Sketch>", "Automatic Sketch Dimensions",
                              "(no category)", ""]

TOLERANCE = 1.0 / 256.0  # feet (about 3/64 in)


class PlanError(ValueError):
    """Bad or unusable input. The command line exits with code 2."""


# ---------------------------------------------------------------- read

def unescape(value):
    """Restore \\uXXXX text that the IronPython read script escapes."""
    if not _is_text(value) or "\\" not in value:
        return value
    out, i = [], 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            n = value[i + 1]
            if n == "\\":
                out.append("\\")
                i += 2
                continue
            if n == "u" and len(value) >= i + 6:
                try:
                    out.append(_chr(int(value[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
        out.append(c)
        i += 1
    return "".join(out)


def _is_text(value):
    try:
        return isinstance(value, basestring)  # noqa: F821  (IronPython 2.7)
    except NameError:
        return isinstance(value, str)


def _chr(code):
    try:
        return unichr(code)  # noqa: F821  (IronPython 2.7)
    except NameError:
        return chr(code)


def load_read(data):
    """The read report, bare or inside a run record ("result")."""
    for _ in range(3):
        if isinstance(data, dict) and data.get("kind") == READ_KIND:
            break
        if isinstance(data, dict) and "result" in data:
            data = data["result"]
            continue
        raise PlanError("Expected a read result of kind '%s'." % READ_KIND)
    if not isinstance(data, dict) or data.get("kind") != READ_KIND:
        raise PlanError("Expected a read result of kind '%s'." % READ_KIND)
    if data.get("escaped"):
        for view in data.get("views") or []:
            view["name"] = unescape(view.get("name"))
            for note in view.get("text_notes") or []:
                note["text"] = unescape(note.get("text"))
                note["type_name"] = unescape(note.get("type_name"))
            for item in (view.get("filled_regions") or []):
                item["type_name"] = unescape(item.get("type_name"))
            for item in (view.get("detail_lines") or []):
                item["style_name"] = unescape(item.get("style_name"))
        for key in ("filled_region_types", "line_styles", "text_note_types"):
            for row in data.get(key) or []:
                row["name"] = unescape(row.get("name"))
    return data


def view_by_id(read, view_id):
    for view in read.get("views") or []:
        if str(view.get("id")) == str(view_id):
            return view
    return None


# --------------------------------------------------------------- style

def style_summary(read, target_view_id=None):
    """Sum up the house style of each reference view.

    Returns {"views": [{"id", "name", "filled_regions", "detail_lines",
    "text_notes", "region_types", "line_styles", "note_types",
    "leader_layouts", "score"}], "closest": view id or None}.
    "score" counts the items. The closest reference is the one with the
    most items that uses at least one filled region and one text note:
    a finished detail, not an empty one.
    """
    rows = []
    for view in read.get("views") or []:
        if target_view_id is not None and str(view.get("id")) == str(target_view_id):
            continue
        regions = view.get("filled_regions") or []
        lines = view.get("detail_lines") or []
        notes = view.get("text_notes") or []
        layouts = {}
        for note in notes:
            key = "%s / %s / %d leader(s)" % (note.get("align") or "?",
                                              note.get("leader_left") or "?",
                                              len(note.get("leaders") or []))
            layouts[key] = layouts.get(key, 0) + 1
        rows.append({
            "id": view.get("id"), "name": view.get("name"),
            "filled_regions": len(regions), "detail_lines": len(lines),
            "text_notes": len(notes),
            "region_types": _counts(r.get("type_name") for r in regions),
            "line_styles": _counts(r.get("style_name") for r in lines),
            "note_types": _counts(r.get("type_name") for r in notes),
            "leader_layouts": sorted(layouts.items(), key=lambda kv: (-kv[1], kv[0])),
            "score": len(regions) + len(lines) + len(notes)})
    finished = [r for r in rows if r["filled_regions"] and r["text_notes"]]
    closest = None
    if finished:
        closest = sorted(finished, key=lambda r: (-r["score"], str(r["id"])))[0]["id"]
    return {"views": rows, "closest": closest}


def _counts(names):
    out = {}
    for name in names:
        name = name or "?"
        out[name] = out.get(name, 0) + 1
    return sorted(out.items(), key=lambda kv: (-kv[1], kv[0]))


def style_text(summary):
    out = ["Reference details (house style):"]
    for r in summary["views"]:
        out.append("- %s (id %s): %d filled regions, %d detail lines, %d text notes."
                   % (r["name"], r["id"], r["filled_regions"], r["detail_lines"], r["text_notes"]))
        for label, key in (("Region types", "region_types"), ("Line styles", "line_styles"),
                           ("Note types", "note_types"), ("Leader layout", "leader_layouts")):
            if r[key]:
                out.append("    %s: %s" % (label, ", ".join("%s x%d" % kv for kv in r[key])))
    if summary["closest"] is not None:
        out.append("Closest finished detail: id %s." % summary["closest"])
    else:
        out.append("No reference view has both a filled region and a text note.")
    return "\n".join(out)


# ---------------------------------------------------------------- copy

def _shift(point, du, dv):
    return [float(point[0]) + du, float(point[1]) + dv]


def copy_items(read, copy_spec):
    """Plan items copied from a reference view by translation.

    copy_spec: {"from_view_id": id, "ids": [element ids] (empty = all
    filled regions and detail lines), "offset": [du, dv]}.
    Text notes are not copied: their text belongs to the new detail.
    Returns (items, warnings).
    """
    view = view_by_id(read, copy_spec.get("from_view_id"))
    if view is None:
        raise PlanError("The reference view %s is not in the read result."
                        % copy_spec.get("from_view_id"))
    offset = copy_spec.get("offset") or [0.0, 0.0]
    du, dv = float(offset[0]), float(offset[1])
    wanted = set(str(i) for i in copy_spec.get("ids") or [])
    items, found = [], set()
    for r in view.get("filled_regions") or []:
        if wanted and str(r.get("id")) not in wanted:
            continue
        found.add(str(r.get("id")))
        items.append({"kind": FILLED_REGION, "type": r.get("type_name"),
                      "loops": [[_shift(p, du, dv) for p in loop] for loop in r.get("loops") or []],
                      "source_id": r.get("id")})
    for r in view.get("detail_lines") or []:
        if wanted and str(r.get("id")) not in wanted:
            continue
        found.add(str(r.get("id")))
        items.append({"kind": DETAIL_LINE, "style": r.get("style_name"),
                      "start": _shift(r["start"], du, dv), "end": _shift(r["end"], du, dv),
                      "source_id": r.get("id")})
    warnings = []
    for missing in sorted(wanted - found):
        warnings.append({"row": "", "blocking": True,
                         "text": "Element %s is not a filled region or detail line in reference view %s."
                                 % (missing, view.get("id"))})
    return items, warnings


# ---------------------------------------------------------------- plan

def to_model(view, uv):
    """A view point (u, v) in feet as a model point [x, y, z]."""
    o, r, up = view["origin"], view["right"], view["up"]
    u, v = float(uv[0]), float(uv[1])
    return [o[i] + r[i] * u + up[i] * v for i in range(3)]


def _lookup(rows, name):
    hits = [r for r in rows or [] if r.get("name") == name]
    return hits


def _inside(crop, uv, tol=TOLERANCE):
    if not crop:
        return True
    return (crop["min"][0] - tol <= uv[0] <= crop["max"][0] + tol
            and crop["min"][1] - tol <= uv[1] <= crop["max"][1] + tol)


def _fmt_pt(p):
    return "(%.3f, %.3f)" % (float(p[0]), float(p[1]))


def _points_text(item):
    kind = item["kind"]
    if kind == FILLED_REGION:
        return "; ".join(" ".join(_fmt_pt(p) for p in loop) for loop in item["loops"])
    if kind == DETAIL_LINE:
        return "%s to %s" % (_fmt_pt(item["start"]), _fmt_pt(item["end"]))
    text = _fmt_pt(item["at"])
    if item.get("leader_end") is not None:
        text += " leader to %s" % _fmt_pt(item["leader_end"])
    return text


def _same(a, b, tol=TOLERANCE):
    return abs(float(a[0]) - float(b[0])) <= tol and abs(float(a[1]) - float(b[1])) <= tol


def compute_plan(read, plan):
    """Turn a plan into a change preview with ordered steps.

    plan: {"view_id": id, "title": optional,
           "items": [{"kind": "filled_region", "type": name, "loops": [[[u, v], ...]]},
                     {"kind": "detail_line", "style": name, "start": [u, v], "end": [u, v]},
                     {"kind": "text_note", "type": name, "text": "...", "at": [u, v],
                      "leader_end": [u, v] or null}],
           "copy": [{"from_view_id", "ids", "offset"}]}
    Copied items come first, then the listed items.
    """
    view = view_by_id(read, plan.get("view_id"))
    warnings = []
    if view is None:
        raise PlanError("The target view %s is not in the read result." % plan.get("view_id"))
    items = []
    for spec in plan.get("copy") or []:
        copied, copy_warnings = copy_items(read, spec)
        items.extend(copied)
        warnings.extend(copy_warnings)
    items.extend(plan.get("items") or [])
    if not items:
        raise PlanError("The plan has no items.")
    crop = view.get("crop_uv")
    before, after, steps = [], [], []
    kinds_used = set()
    for n, item in enumerate(items):
        row = str(n + 1)
        kind = item.get("kind")
        if kind not in KINDS:
            raise PlanError("Item %s: kind must be one of %s." % (row, ", ".join(KINDS)))
        kinds_used.add(kind)
        step = {"step": n + 1, "kind": kind}
        points = []
        if kind == FILLED_REGION:
            name = item.get("type")
            hits = _lookup(read.get("filled_region_types"), name)
            loops = item.get("loops") or []
            if not loops:
                warnings.append({"row": row, "blocking": True, "text": "The filled region has no loop."})
            for loop in loops:
                if len(loop) < 3:
                    warnings.append({"row": row, "blocking": True,
                                     "text": "A filled region loop needs at least 3 points."})
                points.extend(loop)
            step["loops"] = [[[float(p[0]), float(p[1])] for p in loop] for loop in loops]
            step["loops_model"] = [[to_model(view, p) for p in loop] for loop in loops]
            label = name
        elif kind == DETAIL_LINE:
            name = item.get("style")
            hits = _lookup(read.get("line_styles"), name)
            if _same(item["start"], item["end"]):
                warnings.append({"row": row, "blocking": True, "text": "The detail line has zero length."})
            points = [item["start"], item["end"]]
            step["start"] = [float(item["start"][0]), float(item["start"][1])]
            step["end"] = [float(item["end"][0]), float(item["end"][1])]
            step["start_model"] = to_model(view, item["start"])
            step["end_model"] = to_model(view, item["end"])
            label = name
        else:
            name = item.get("type")
            hits = _lookup(read.get("text_note_types"), name)
            text = item.get("text") or ""
            if not text.strip():
                warnings.append({"row": row, "blocking": True, "text": "The text note has no text."})
            points = [item["at"]]
            step["text"] = text
            step["at"] = [float(item["at"][0]), float(item["at"][1])]
            step["at_model"] = to_model(view, item["at"])
            end = item.get("leader_end")
            if end is not None:
                points.append(end)
                step["leader_end"] = [float(end[0]), float(end[1])]
                step["leader_end_model"] = to_model(view, end)
                if _same(end, item["at"]):
                    warnings.append({"row": row, "blocking": False,
                                     "text": "The leader ends at the note point. It has no length."})
            step["align"] = item.get("align") or "Center"
            step["leader_left"] = item.get("leader_left") or "TopLine"
            label = name
        if len(hits) == 1:
            step["type_id"] = hits[0]["id"]
        elif not hits:
            warnings.append({"row": row, "blocking": True,
                             "text": "%s type or style '%s' is not in the model."
                                     % (KIND_LABELS[kind], name)})
        else:
            warnings.append({"row": row, "blocking": True,
                             "text": "%d types or styles are named '%s'. Use the id."
                                     % (len(hits), name)})
        step["type_name"] = name
        outside = [p for p in points if not _inside(crop, p)]
        if outside:
            warnings.append({"row": row, "blocking": True,
                             "text": "%d point(s) are outside the crop region, for example %s. "
                                     "The element would not show." % (len(outside), _fmt_pt(outside[0]))})
        if item.get("source_id") is not None:
            step["source_id"] = item["source_id"]
        steps.append(step)
        before.append([row, KIND_LABELS[kind], "", "", ""])
        after.append([row, KIND_LABELS[kind], label or "", _points_text(dict(item, kind=kind)),
                      step.get("text", "")])
    existing = (len(view.get("filled_regions") or []) + len(view.get("detail_lines") or [])
                + len(view.get("text_notes") or []))
    counts = dict((k, sum(1 for s in steps if s["kind"] == k)) for k in KINDS)
    notes = ["View '%s' (id %s): add %d filled regions, %d detail lines, %d text notes."
             % (view.get("name"), view.get("id"), counts[FILLED_REGION], counts[DETAIL_LINE],
                counts[TEXT_NOTE])]
    if existing:
        notes.append("The view already has %d annotation elements. The plan keeps them." % existing)
    expected = []
    if FILLED_REGION in kinds_used:
        expected = list(FILLED_REGION_SIDE_EFFECTS)
        notes.append("Each filled region adds its own sketch lines, automatic sketch dimensions, "
                     "and a sketch with no category. The side-effects check expects them.")
    blocked = any(w.get("blocking") for w in warnings)
    columns = ["Step", "Kind", "Type or style", "Points (view ft)", "Text"]
    return {"kind": "change-preview", "recipe": "detail-annotation",
            "title": plan.get("title") or "Annotate detail view %s" % view.get("name"),
            "keyColumn": "Step", "columns": columns, "changedColumns": columns[2:],
            "before": before, "after": after, "notes": notes, "warnings": warnings,
            "blocked": blocked, "steps": [] if blocked else steps,
            "view": {"id": view.get("id"), "name": view.get("name"), "origin": view["origin"],
                     "right": view["right"], "up": view["up"], "crop_uv": crop},
            "edited_categories": sorted(set(EDITED_CATEGORIES[k] for k in kinds_used)),
            "expected_dependent_categories": expected,
            "ownership_ids": [view.get("id")],
            "planned_steps": steps}


def text_table(preview, limit=10):
    rows = preview["after"]
    shown = rows if len(rows) <= 2 * limit else rows[:limit] + [["...", "", "", "", ""]] + rows[-limit:]
    out = [preview["title"]]
    for r in shown:
        out.append("  %s  %s  %s  %s%s" % (r[0], r[1], r[2], r[3], ("  \"%s\"" % r[4]) if r[4] else ""))
    out.extend(preview["notes"])
    blocking = [w for w in preview["warnings"] if w.get("blocking")]
    out.append("Steps: %d. Warnings: %d (%d blocking)." % (len(rows), len(preview["warnings"]), len(blocking)))
    for w in preview["warnings"]:
        out.append("%s step %s: %s" % ("BLOCKING" if w.get("blocking") else "WARN", w.get("row") or "-", w["text"]))
    if preview["blocked"]:
        out.append("BLOCKED: do not offer Apply.")
    return "\n".join(out)


# ------------------------------------------------------------- mapping

def mapping_from_points(view_a, pixel_a, view_b, pixel_b, max_skew=0.02):
    """Map view (u, v) to capture pixels from two known points.

    Pick two points that differ in both u and v, for example two corners
    of a reference filled region that show in the capture. Image y goes
    down, view v goes up. Returns (mapping, warnings).
    """
    du = float(view_b[0]) - float(view_a[0])
    dv = float(view_b[1]) - float(view_a[1])
    if abs(du) < TOLERANCE or abs(dv) < TOLERANCE:
        raise PlanError("The two known points must differ in both u and v.")
    sx = (float(pixel_b[0]) - float(pixel_a[0])) / du
    sy = -(float(pixel_b[1]) - float(pixel_a[1])) / dv
    if sx <= 0 or sy <= 0:
        raise PlanError("The known points give a mirrored mapping. Check the point order.")
    warnings = []
    if abs(sx - sy) / max(sx, sy) > max_skew:
        warnings.append("The two known points give different x and y scales (%.2f and %.2f px/ft). "
                        "Check the points. The capture can be stretched or the points wrong." % (sx, sy))
    mapping = {"scale_x": sx, "scale_y": sy,
               "offset_x": float(pixel_a[0]) - sx * float(view_a[0]),
               "offset_y": float(pixel_a[1]) + sy * float(view_a[1])}
    return mapping, warnings


def mapping_from_crop(crop, width, height, margin=0.0):
    """Map the crop region to fill the image (centered, same scale on x and y).

    Use it when there is no capture, or when the capture shows exactly the
    crop region. A panned or zoomed view breaks this mapping: use
    mapping_from_points then.
    """
    if not crop:
        raise PlanError("The view has no crop region. Use two known points.")
    du = float(crop["max"][0]) - float(crop["min"][0])
    dv = float(crop["max"][1]) - float(crop["min"][1])
    if du <= 0 or dv <= 0:
        raise PlanError("The crop region has no size.")
    s = min((width - 2 * margin) / du, (height - 2 * margin) / dv)
    ox = (width - s * du) / 2.0 - s * float(crop["min"][0])
    oy = (height - s * dv) / 2.0 + s * float(crop["max"][1])
    return {"scale_x": s, "scale_y": s, "offset_x": ox, "offset_y": oy}


def to_pixel(mapping, uv):
    return [mapping["offset_x"] + mapping["scale_x"] * float(uv[0]),
            mapping["offset_y"] - mapping["scale_y"] * float(uv[1])]


# ----------------------------------------------------------------- svg

def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _pts(mapping, points):
    return " ".join("%.1f,%.1f" % tuple(to_pixel(mapping, p)) for p in points)


def svg_overlay(preview, mapping, width, height, image_href=None):
    """The planned items as SVG over the capture (or over a blank sheet)."""
    steps = preview.get("planned_steps") or preview.get("steps") or []
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="100%%" '
           'role="img" aria-label="Planned annotation">' % (width, height)]
    if image_href:
        out.append('<image href="%s" x="0" y="0" width="%d" height="%d"/>' % (_esc(image_href), width, height))
    else:
        out.append('<rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/>' % (width, height))
    crop = (preview.get("view") or {}).get("crop_uv")
    if crop:
        a = to_pixel(mapping, [crop["min"][0], crop["max"][1]])
        b = to_pixel(mapping, [crop["max"][0], crop["min"][1]])
        out.append('<rect class="crop" x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" '
                   'stroke="#888888" stroke-dasharray="6 4"/>' % (a[0], a[1], b[0] - a[0], b[1] - a[1]))
    for s in steps:
        tag = 'data-step="%s"' % s["step"]
        if s["kind"] == FILLED_REGION:
            for loop in s["loops"]:
                out.append('<polygon %s points="%s" fill="#e8590c" fill-opacity="0.35" '
                           'stroke="#e8590c" stroke-width="1.5"><title>Step %s: %s</title></polygon>'
                           % (tag, _pts(mapping, loop), s["step"], _esc(s.get("type_name") or "")))
        elif s["kind"] == DETAIL_LINE:
            a = to_pixel(mapping, s["start"])
            b = to_pixel(mapping, s["end"])
            out.append('<line %s x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#c92a2a" '
                       'stroke-width="2"><title>Step %s: %s</title></line>'
                       % (tag, a[0], a[1], b[0], b[1], s["step"], _esc(s.get("type_name") or "")))
        else:
            p = to_pixel(mapping, s["at"])
            if s.get("leader_end") is not None:
                e = to_pixel(mapping, s["leader_end"])
                out.append('<line %s x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#1971c2" '
                           'stroke-width="1.5"/>' % (tag, p[0], p[1], e[0], e[1]))
                out.append('<circle cx="%.1f" cy="%.1f" r="3" fill="#1971c2"/>' % (e[0], e[1]))
            anchor = {"Left": "start", "Right": "end"}.get(s.get("align"), "middle")
            lines = (s.get("text") or "").split("\n")
            for i, line in enumerate(lines):
                out.append('<text %s x="%.1f" y="%.1f" font-family="Arial, sans-serif" font-size="13" '
                           'fill="#1971c2" text-anchor="%s">%s</text>'
                           % (tag, p[0], p[1] - 4 - 15 * (len(lines) - 1 - i), anchor, _esc(line)))
    out.append("</svg>")
    return "\n".join(out)


def html_page(preview, svg, mapping_note=""):
    """A self-contained page: the drawing first, the table second."""
    rows = []
    for b, a in zip(preview["before"], preview["after"]):
        rows.append("<tr>%s</tr>" % "".join("<td>%s</td>" % _esc(v) for v in a))
    warn = "".join('<li class="%s">Step %s: %s</li>' % ("block" if w.get("blocking") else "warn",
                                                        _esc(w.get("row") or "-"), _esc(w["text"]))
                   for w in preview["warnings"])
    notes = "".join("<li>%s</li>" % _esc(n) for n in preview["notes"])
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Detail annotation preview</title>
<style>
:root { --bg: #ffffff; --fg: #1d1d1f; --muted: #6b6b70; --line: #d9d9de; }
@media (prefers-color-scheme: dark) { :root { --bg: #1b1b1d; --fg: #ececf1; --muted: #a0a0a8; --line: #3a3a40; } }
body { background: var(--bg); color: var(--fg); font: 14px/1.45 system-ui, sans-serif; margin: 0; padding: 16px; }
h1 { font-size: 18px; margin: 0 0 4px; } p.sub { color: var(--muted); margin: 0 0 12px; }
.drawing { border: 1px solid var(--line); background: #fff; max-width: 1100px; }
.legend span { display: inline-block; margin-right: 16px; }
.legend i { display: inline-block; width: 12px; height: 12px; margin-right: 4px; vertical-align: -1px; }
table { border-collapse: collapse; margin-top: 12px; width: 100%%; max-width: 1100px; }
td, th { border-bottom: 1px solid var(--line); padding: 4px 8px; text-align: left; vertical-align: top; }
li.block { color: #c92a2a; font-weight: 600; } li.warn { color: #b35c00; }
.wrap { overflow-x: auto; }
</style></head><body>
<h1>%s</h1>
<p class="sub">Planned annotation over a capture of the view. Nothing is in the model yet. %s</p>
<p class="legend"><span><i style="background:#e8590c"></i>Filled region</span><span><i style="background:#c92a2a"></i>Detail line</span><span><i style="background:#1971c2"></i>Text note and leader</span></p>
<div class="drawing">%s</div>
<ul>%s</ul>
<ul>%s</ul>
<div class="wrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>
</body></html>
""" % (_esc(preview["title"]), _esc(mapping_note), svg, notes, warn,
       "".join("<th>%s</th>" % _esc(c) for c in preview["columns"]), "".join(rows))


def data_uri(png_bytes):
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def png_size(png_bytes):
    """(width, height) from a PNG header."""
    if png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise PlanError("The capture is not a PNG file.")
    return struct.unpack(">II", png_bytes[16:24])


# ------------------------------------------------------------- compare

def compare(preview, result, tol=TOLERANCE):
    """Differences between the preview steps and an apply result.

    result: {"created": [{"step", "kind", "ids", "type_id", "loops" |
    "start"/"end" | "at"/"text"/"leader_end"}]} with points in view
    coordinates, re-read after the transaction steps.
    """
    if isinstance(result, dict) and "result" in result and "created" not in result:
        result = result["result"]
    if not isinstance(result, dict) or "created" not in result:
        raise PlanError("The run has no 'created' list (check status and error).")
    escaped = result.get("escaped")
    got = dict((int(r["step"]), r) for r in result["created"])
    diffs = []
    for s in preview.get("steps") or []:
        r = got.get(int(s["step"]))
        if r is None:
            diffs.append("Step %s: not created." % s["step"])
            continue
        if r.get("kind") != s["kind"]:
            diffs.append("Step %s: kind %s, expected %s." % (s["step"], r.get("kind"), s["kind"]))
            continue
        if str(r.get("type_id")) != str(s.get("type_id")):
            diffs.append("Step %s: type %s, expected %s." % (s["step"], r.get("type_id"), s.get("type_id")))
        if s["kind"] == FILLED_REGION:
            if not _same_loops(s["loops"], r.get("loops") or [], tol):
                diffs.append("Step %s: the filled region boundary differs." % s["step"])
        elif s["kind"] == DETAIL_LINE:
            ends = [r.get("start"), r.get("end")]
            if None in ends or not ((_same(s["start"], ends[0], tol) and _same(s["end"], ends[1], tol))
                                    or (_same(s["start"], ends[1], tol) and _same(s["end"], ends[0], tol))):
                diffs.append("Step %s: the line ends differ." % s["step"])
        else:
            text = unescape(r.get("text")) if escaped else r.get("text")
            if (text or "").replace("\r", "\n") != (s.get("text") or "").replace("\r", "\n"):
                diffs.append("Step %s: text %r, expected %r." % (s["step"], text, s.get("text")))
            if r.get("at") is None or not _same(s["at"], r["at"], tol):
                diffs.append("Step %s: the note point differs." % s["step"])
            if s.get("leader_end") is not None:
                if r.get("leader_end") is None or not _same(s["leader_end"], r["leader_end"], tol):
                    diffs.append("Step %s: the leader end differs." % s["step"])
    extra = sorted(set(got) - set(int(s["step"]) for s in preview.get("steps") or []))
    for n in extra:
        diffs.append("Step %s: created but not in the preview." % n)
    return diffs


def _same_loops(expected, actual, tol):
    """Same loops, in any order, each with the same corner points in any start and direction."""
    if len(expected) != len(actual):
        return False
    remaining = list(actual)
    for loop in expected:
        hit = None
        for i, other in enumerate(remaining):
            if _same_ring(loop, other, tol):
                hit = i
                break
        if hit is None:
            return False
        remaining.pop(hit)
    return True


def _same_ring(a, b, tol):
    if len(a) != len(b):
        return False
    n = len(a)
    for start in range(n):
        for step in (1, -1):
            if all(_same(a[i], b[(start + step * i) % n], tol) for i in range(n)):
                return True
    return False


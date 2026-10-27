# -*- coding: utf-8 -*-
"""Pure material-audit computation for the am-material-audit skill.

Runs under IronPython 2.7 (inside Revit) and CPython 3 (tests, audit_report.py).
No f-strings, no type annotations, no nonlocal. No Revit imports: this module
never touches the model. It only turns a read_materials.py read result into
an audit: rows with used/unused, duplicate groups and low-contrast flags.

Material dict shape (what material_audit.py returns):
    {"id": 123, "name": "Floor Finish - Oak",
     "shading": {"r": 128, "g": 64, "b": 32} or None,
     "shading_from_render_appearance": False,
     "transparency": 0,
     "surface_foreground": {"pattern": "Solid fill", "pattern_id": 45,
                            "color": {"r": 255, "g": 255, "b": 255}} or None,
     "surface_background": {"pattern": "<none>", "pattern_id": -1, "color": None},
     "cut_foreground": {...} or None, "cut_background": {...} or None}
"""
import math
import re

# Two pattern colors closer than this (Euclidean distance in RGB space, 0-441)
# read as one color on screen, so the pattern is hard to see. The value is a
# named constant so the SKILL.md and the tests pin the same number.
LOW_CONTRAST_DISTANCE = 32.0

_ESC_RE = re.compile(r"\\(\\|u[0-9a-fA-F]{4})")

# What the scoped unused check does NOT cover. The read script reports this
# list too; the default here covers hand-made read results (tests, fixtures).
NOT_CHECKED_DEFAULT = [
    "materials assigned directly to model elements (element material parameters)",
    "painted faces (Paint tool)",
    "materials in linked models",
    "materials used only inside in-place families",
    "materials used only by appearance or material assets",
]


def rgb_text(color):
    """{"r": 128, "g": 64, "b": 32} -> "128, 64, 32". None -> "—"."""
    if color is None:
        return "—"
    return "%d, %d, %d" % (int(color["r"]), int(color["g"]), int(color["b"]))


def color_tuple(color):
    """{"r","g","b"} dict -> (r, g, b) tuple. None -> None."""
    if color is None:
        return None
    return (int(color["r"]), int(color["g"]), int(color["b"]))


def color_distance(c1, c2):
    """Euclidean distance between two {"r","g","b"} colors. None input -> None."""
    if c1 is None or c2 is None:
        return None
    dr = int(c1["r"]) - int(c2["r"])
    dg = int(c1["g"]) - int(c2["g"])
    db = int(c1["b"]) - int(c2["b"])
    return math.sqrt(dr * dr + dg * dg + db * db)


def is_low_contrast(fg_color, bg_color, threshold=LOW_CONTRAST_DISTANCE):
    """True when both surface colors exist and sit closer than threshold."""
    d = color_distance(fg_color, bg_color)
    if d is None:
        return False
    return d < threshold


def duplicate_key(material):
    """Colors that define a duplicate: shading, surface foreground, background.

    Pattern names are not part of the key: two materials with the same colors
    are duplicates even when their pattern names differ. The table shows the
    pattern names, so the user can see that difference.
    """
    def entry_color(entry):
        if not entry:
            return None
        return color_tuple(entry.get("color"))
    return (color_tuple(material.get("shading")),
            entry_color(material.get("surface_foreground")),
            entry_color(material.get("surface_background")))


def find_duplicates(materials):
    """Groups of two or more materials with the same colors (see duplicate_key).

    A material with no shading color cannot be compared, so it never joins a
    group. Returns groups in first-seen order.
    """
    groups = {}
    order = []
    for m in materials:
        key = duplicate_key(m)
        if key[0] is None:
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(m)
    return [groups[k] for k in order if len(groups[k]) >= 2]


def unescape(text):
    """Reverse the IronPython ASCII escaping done by read_materials.py."""
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
    """Turn a read_materials.py result (or the full run JSON) into materials.

    Returns (materials, result). The result is unwrapped from the run JSON
    when needed, and names are unescaped when the result says "escaped".
    """
    if "result" in result and "materials" not in result:
        result = result["result"]
    materials = []
    for m in result["materials"]:
        d = dict(m)
        if result.get("escaped"):
            d["name"] = unescape(d["name"])
        materials.append(d)
    return materials, result


def pattern_text(entry):
    """{"pattern","color"} -> {"pattern","color"} with RGB text. None -> None."""
    if entry is None:
        return None
    return {"pattern": entry.get("pattern") or "<none>",
            "color": rgb_text(entry.get("color"))}


def audit(read_result):
    """Build the audit from a read_materials.py read result.

    Returns {"prefix","model","revit_year","timestamp","rows","unused",
    "duplicates","low_contrast","not_checked","counts"}. Each row has "id",
    "name", "shading" (RGB text), "shading_from_render_appearance",
    "transparency", "surface_foreground" / "surface_background" (pattern and
    RGB text), "cut_foreground" / "cut_background" (same, or None when the
    material has no cut pattern), "used" ("type structure", "family", or
    "unused (scoped check)"), "duplicate_group" (1-based group number or
    None) and "low_contrast" (bool).
    """
    materials, result = load_read_result(read_result)
    used_type = set(result.get("used_in_type_structure") or [])
    used_family = set(result.get("used_in_family") or [])
    duplicates = find_duplicates(materials)
    group_of = {}
    for i, group in enumerate(duplicates, 1):
        for m in group:
            group_of[m["id"]] = i
    rows = []
    for m in materials:
        fg = m.get("surface_foreground") or {}
        bg = m.get("surface_background") or {}
        if m["id"] in used_type:
            used = "type structure"
        elif m["id"] in used_family:
            used = "family"
        else:
            used = "unused (scoped check)"
        rows.append({
            "id": m["id"],
            "name": m["name"],
            "shading": rgb_text(m.get("shading")),
            "shading_from_render_appearance": bool(m.get("shading_from_render_appearance")),
            "transparency": m.get("transparency"),
            "surface_foreground": pattern_text(m.get("surface_foreground")),
            "surface_background": pattern_text(m.get("surface_background")),
            "cut_foreground": pattern_text(m.get("cut_foreground")),
            "cut_background": pattern_text(m.get("cut_background")),
            "used": used,
            "duplicate_group": group_of.get(m["id"]),
            "low_contrast": is_low_contrast(fg.get("color"), bg.get("color")),
        })
    unused = [r for r in rows if r["used"] == "unused (scoped check)"]
    low = [r for r in rows if r["low_contrast"]]
    return {
        "prefix": result.get("prefix", ""),
        "model": result.get("model", ""),
        "revit_year": result.get("revit_year", ""),
        "timestamp": result.get("timestamp", ""),
        "rows": rows,
        "unused": [r["name"] for r in unused],
        "duplicates": [[m["name"] for m in g] for g in duplicates],
        "low_contrast": [r["name"] for r in low],
        "not_checked": list(result.get("not_checked") or NOT_CHECKED_DEFAULT),
        "counts": {"matched": len(rows),
                   "used": len(rows) - len(unused),
                   "unused": len(unused),
                   "duplicate_groups": len(duplicates),
                   "low_contrast": len(low)},
    }


def _cell(text, width):
    """Pad or cut a table cell to width. Text is ASCII or short on purpose."""
    text = "" if text is None else str(text)
    if len(text) > width:
        text = text[:width - 1] + "~"
    return text + " " * (width - len(text))


def render_table(audit_result):
    """Plain-text audit table plus summary, for the terminal and for chat.

    Shows RGB values by default. Cut patterns show only when present.
    """
    rows = audit_result["rows"]
    lines = []
    lines.append("Materials starting with %r: %d matched, %d used, %d unused (scoped check)" % (
        audit_result["prefix"], audit_result["counts"]["matched"],
        audit_result["counts"]["used"], audit_result["counts"]["unused"]))
    if not rows:
        lines.append("No materials start with this prefix.")
        return "\n".join(lines)
    widths = (24, 14, 4, 28, 28, 22, 21, 14)
    header = [_cell(t, w) for t, w in zip(
        ["Material", "Shading (RGB)", "Tr%", "Surface FG pattern / RGB",
         "Surface BG pattern / RGB", "Cut pattern", "Used", "Flags"], widths)]
    lines.append(" | ".join(header))
    lines.append("-+-".join(["-" * w for w in widths]))
    for r in rows:
        def fg_bg(entry):
            if entry is None:
                return "—"
            return "%s (%s)" % (entry["pattern"], entry["color"])
        cut = []
        for key in ("cut_foreground", "cut_background"):
            entry = r[key]
            if entry is not None:
                cut.append("%s: %s (%s)" % (
                    "FG" if key == "cut_foreground" else "BG",
                    entry["pattern"], entry["color"]))
        flags = []
        if r["duplicate_group"] is not None:
            flags.append("dup #%d" % r["duplicate_group"])
        if r["low_contrast"]:
            flags.append("low contrast")
        if r["shading_from_render_appearance"]:
            flags.append("color from render appearance")
        cells = [_cell(r["name"], widths[0]),
                 _cell(r["shading"], widths[1]),
                 _cell(r["transparency"], widths[2]),
                 _cell(fg_bg(r["surface_foreground"]), widths[3]),
                 _cell(fg_bg(r["surface_background"]), widths[4]),
                 _cell("; ".join(cut) if cut else "—", widths[5]),
                 _cell(r["used"], widths[6]),
                 _cell(", ".join(flags), widths[7])]
        lines.append(" | ".join(cells))
    lines.append("")
    if audit_result["unused"]:
        lines.append("Unused (scoped check): %s" % ", ".join(audit_result["unused"]))
    for i, group in enumerate(audit_result["duplicates"], 1):
        lines.append("Duplicate group #%d (same colors): %s" % (i, ", ".join(group)))
    if audit_result["low_contrast"]:
        lines.append("Low pattern contrast: %s" % ", ".join(audit_result["low_contrast"]))
    lines.append("Not checked by the scoped unused check: %s" % (
        "; ".join(audit_result["not_checked"])))
    return "\n".join(lines)

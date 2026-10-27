# -*- coding: utf-8 -*-
"""READ step for the material-colors recipe. Read-only (run_query / --mode=query).

Returns every material in the active document with its current Shading
color (Material.Color) and its Surface Foreground Pattern color, plus
the categories of the elements that use each material. The used-by
categories feed the preview's expected_dependent_categories (issue #28):
floors and tags that use a material redraw when the material changes.

The used-by scan walks the model once and stops at MAX_SCAN elements;
"used_by_truncated" is true when it stopped early, so the expected
dependents list may miss categories on a very large model.

result = {"document": <title>, "count": N,
          "materials": [{"id", "name", "shading": [r, g, b] or None,
                         "surface_pattern_id", "surface_pattern_name",
                         "surface_pattern_color": [r, g, b] or None,
                         "used_by_categories": [...],
                         "used_by_truncated": bool}, ...]}
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
from pyrevit.api import DB


def eid_int(element_id):
    # Revit 2024+ has ElementId.Value (Int64); IntegerValue was removed in 2026.
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


import sys

# The agent runtime's IronPython JSON encoder fails on non-ASCII text
# ("'unknown' codec can't decode byte 0xe9"). Under IronPython, escape text to
# ASCII ("\\" -> "\\\\", "e-acute" -> "\\u00e9") and set "escaped": true.
# material_colors.load_read_result() reverses it. CPython returns plain text.
ESCAPE = sys.platform == "cli"

# The used-by scan stops here, so a huge model still answers in time.
MAX_SCAN = 20000


def txt(s):
    if not ESCAPE:
        return s
    out = []
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif ord(c) < 128:
            out.append(c)
        else:
            out.append("\\u%04x" % ord(c))
    return "".join(out)


def rgb(color):
    if color is None:
        return None
    try:
        return [int(color.Red), int(color.Green), int(color.Blue)]
    except Exception:
        return None


def pattern_color(mat):
    # Material.SurfaceForegroundPatternColor exists in Revit 2019 and later.
    # Older versions raise AttributeError; the panel then shows no pattern color.
    try:
        return rgb(mat.SurfaceForegroundPatternColor)
    except Exception:
        return None


rows = []
for mat in DB.FilteredElementCollector(doc).OfClass(DB.Material):
    pid = mat.SurfaceForegroundPatternId
    pname = None
    if pid is not None and pid.IntegerValue > 0:
        try:
            pat = doc.GetElement(pid)
            pname = txt(pat.Name) if pat is not None else None
        except Exception:
            pname = None
    rows.append({
        "id": eid_int(mat.Id),
        "name": txt(mat.Name),
        "shading": rgb(mat.Color),
        "surface_pattern_id": eid_int(pid) if pid is not None else None,
        "surface_pattern_name": pname,
        "surface_pattern_color": pattern_color(mat),
        "used_by_categories": [],
        "used_by_truncated": False,
    })
rows.sort(key=lambda r: r["name"].lower())

# One pass over the model: which categories use each material.
by_id = dict((r["id"], r) for r in rows)
used = dict((r["id"], set()) for r in rows)
scanned = 0
truncated = False
for el in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():
    if scanned >= MAX_SCAN:
        truncated = True
        break
    scanned += 1
    try:
        mids = el.GetMaterialIds(False)
    except Exception:
        continue
    if not mids:
        continue
    cat = None
    try:
        if el.Category is not None:
            cat = txt(el.Category.Name)
    except Exception:
        cat = None
    if cat is None:
        continue
    for mid in mids:
        mid_int = eid_int(mid)
        if mid_int in used:
            used[mid_int].add(cat)
for r in rows:
    r["used_by_categories"] = sorted(used[r["id"]])
    r["used_by_truncated"] = truncated

result = {"document": txt(doc.Title), "count": len(rows), "escaped": ESCAPE,
          "materials": rows}

# -*- coding: utf-8 -*-
"""READ step for the sheet renumber recipe. Read-only (run_query / --mode=query).

Returns every ViewSheet in the active document, placeholders included,
because placeholders also hold a sheet number that must stay unique.

result = {"document": <title>, "count": N,
          "sheets": [{"id", "number", "name", "placeholder"}, ...]}
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
# ASCII ("\\" -> "\\\\", "é" -> "\\u00e9") and set "escaped": true.
# sheet_shift.load_read_result() reverses it. CPython returns plain text.
ESCAPE = sys.platform == "cli"


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


rows = []
for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
    rows.append({
        "id": eid_int(vs.Id),
        "number": txt(vs.SheetNumber),
        "name": txt(vs.Name),
        "placeholder": bool(vs.IsPlaceholder),
    })
rows.sort(key=lambda r: r["number"])
result = {"document": txt(doc.Title), "count": len(rows), "escaped": ESCAPE,
          "sheets": rows}

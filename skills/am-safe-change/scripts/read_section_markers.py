# -*- coding: utf-8 -*-
"""READ step for new detail sections (issue #257). Read-only (run_query).

Lists the cut line of every section and detail view in the model (not
templates), for the duplicate check in section_mark_plan.py.

inputs: {} or {"view_types": ["Section", "Detail"]}

For each view the cut line is read from its CropBox. The box X axis is
right on screen, Y is up and Z points towards the viewer, so the cut
plane is the box face nearest the viewer (local z = Max.Z). The line runs
from local (Min.X, *, Max.Z) to (Max.X, *, Max.Z), in plan.
Reference sections (view-specific markers that point at another view)
are not views. This script does not list them.

result = {"document", "escaped",
          "markers": [{"id", "name", "view_type", "start": [x, y], "end": [x, y],
                       "z_min", "z_max", "view_direction": [x, y, z]}]}
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import sys

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"  # IronPython result encoder is ASCII-only (see read_sheets.py)
MAX_VIEWS = 5000  # the query budget in am-revit-api-docs


def txt(s):
    if s is None or not ESCAPE:
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


def id_int(element_id):
    try:
        return int(element_id.Value)        # Revit 2024+
    except AttributeError:
        return int(element_id.IntegerValue)  # removed in Revit 2026


wanted = set(inputs.get("view_types") or ["Section", "Detail"])  # noqa: F821
markers = []
for view in DB.FilteredElementCollector(doc).OfClass(DB.ViewSection):  # noqa: F821
    if view.IsTemplate or str(view.ViewType) not in wanted:
        continue
    if len(markers) >= MAX_VIEWS:
        raise ValueError("More than %d section views. Narrow the scope first." % MAX_VIEWS)
    box = view.CropBox
    if box is None:
        continue
    t = box.Transform
    a = t.OfPoint(DB.XYZ(box.Min.X, box.Min.Y, box.Max.Z))
    b = t.OfPoint(DB.XYZ(box.Max.X, box.Min.Y, box.Max.Z))
    top = t.OfPoint(DB.XYZ(box.Min.X, box.Max.Y, box.Max.Z))
    d = view.ViewDirection
    markers.append({"id": id_int(view.Id), "name": txt(view.Name), "view_type": str(view.ViewType),
                    "start": [a.X, a.Y], "end": [b.X, b.Y],
                    "z_min": min(a.Z, top.Z), "z_max": max(a.Z, top.Z),
                    "view_direction": [d.X, d.Y, d.Z]})

result = {"document": txt(doc.Title), "markers": markers, "escaped": ESCAPE}  # noqa: F821

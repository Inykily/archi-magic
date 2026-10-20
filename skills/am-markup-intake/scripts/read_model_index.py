# -*- coding: utf-8 -*-
"""MAP step for am-markup-intake. READ ONLY: run with run_query (--mode=query).

Lists what markups can point at, so consolidate.py --model can match them:
  sheets: number, name, placeholder, and the views placed on each sheet
          (detail number, view name, view type)
  rooms:  number, name, level (placed rooms only)
  doors / windows: Mark values (only the marks, no geometry)

It never starts a transaction, never changes the active view or the selection.
Runs under IronPython 2.7 and CPython 3 (no f-strings).

result = {"kind": "markup-model-index", "document": <title>, "escaped": bool,
          "sheets": [{"number", "name", "placeholder",
                      "views": [{"detail", "name", "type"}]}],
          "rooms": [{"number", "name", "level"}],
          "doorMarks": [...], "windowMarks": [...]}
"""
import sys

from pyrevit.api import DB

# The agent's IronPython JSON writer fails on non-ASCII text. Escape to ASCII
# under IronPython ("\\u00e9") and set "escaped": true; consolidate.py reverses it.
ESCAPE = sys.platform == "cli"


def txt(s):
    if s is None:
        return ""
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


def pstr(el, bip):
    p = el.get_Parameter(bip)
    if p is None:
        return ""
    return p.AsString() or ""


sheets = []
for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
    views = []
    if not vs.IsPlaceholder:
        for vp_id in vs.GetAllViewports():
            vp = doc.GetElement(vp_id)
            if vp is None:
                continue
            v = doc.GetElement(vp.ViewId)
            views.append({
                "detail": txt(pstr(vp, DB.BuiltInParameter.VIEWPORT_DETAIL_NUMBER)),
                "name": txt(v.Name if v is not None else ""),
                "type": str(v.ViewType) if v is not None else "",
            })
    views.sort(key=lambda r: r["detail"])
    sheets.append({"number": txt(vs.SheetNumber), "name": txt(vs.Name),
                   "placeholder": bool(vs.IsPlaceholder), "views": views})
sheets.sort(key=lambda r: r["number"])

rooms = []
rc = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms)
for r in rc.WhereElementIsNotElementType():
    if r.Location is None:  # unplaced room
        continue
    lvl = doc.GetElement(r.LevelId)
    rooms.append({"number": txt(pstr(r, DB.BuiltInParameter.ROOM_NUMBER)),
                  "name": txt(pstr(r, DB.BuiltInParameter.ROOM_NAME)),
                  "level": txt(lvl.Name if lvl is not None else "")})
rooms.sort(key=lambda r: r["number"])


def marks(bic):
    out = set()
    col = DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType()
    for e in col:
        m = pstr(e, DB.BuiltInParameter.ALL_MODEL_MARK)
        if m:
            out.add(txt(m))
    return sorted(out)


result = {"kind": "markup-model-index", "document": txt(doc.Title), "escaped": ESCAPE,
          "sheets": sheets, "rooms": rooms,
          "doorMarks": marks(DB.BuiltInCategory.OST_Doors),
          "windowMarks": marks(DB.BuiltInCategory.OST_Windows)}

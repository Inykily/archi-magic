# -*- coding: utf-8 -*-
"""READ step for the element-transforms recipe. Read-only (run_query / --mode=query).

inputs: {"ids": [123, 456]}
    or  {"request_path": "C:/.../transforms.json"}   (the viewer's element-transforms JSON)

result = {"document", "lengthUnit" (Revit unit type id of project length display),
          "escaped": bool,
          "elements": [{"id", "exists", "name", "category",
                        "kind": "point"|"curve"|"none",
                        "point": [x, y, z] ft (location point, or curve midpoint),
                        "rotation": deg in [0, 360) or null,
                        "pinned", "groupId" (0 = none),
                        "hostId" (0 = none, or the host is a Level), "hostCategory",
                        "dependents": [ids of family instances hosted by this element],
                        "levelId", "isView", "viewSpecific"}]}
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import io
import json
import math
import sys

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"  # IronPython result encoder is ASCII-only (see read_sheets.py)


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


def eid_int(element_id):
    try:
        return int(element_id.Value)         # Revit 2024+
    except AttributeError:
        return int(element_id.IntegerValue)  # removed in Revit 2026


def make_id(i):
    try:
        import System
        return DB.ElementId(System.Int64(i))  # Revit 2024+ (2026 has only Int64)
    except Exception:
        return DB.ElementId(int(i))


def xyz(p):
    return [float(p.X), float(p.Y), float(p.Z)]


def norm_deg(rad):
    d = math.degrees(rad) % 360.0
    return 0.0 if abs(d) < 1e-12 or d >= 360.0 - 1e-12 else d


def requested_ids():
    if inputs.get("ids"):
        return [int(i) for i in inputs["ids"]]
    path = inputs.get("request_path")
    if not path:
        raise ValueError("inputs needs ids or request_path")
    with io.open(path, "r", encoding="utf-8-sig") as f:
        req = json.loads(f.read())
    return [int(it["id"]) for it in req.get("items") or [] if "id" in it]


def length_unit():
    try:
        return doc.GetUnits().GetFormatOptions(DB.SpecTypeId.Length).GetUnitTypeId().TypeId
    except Exception:
        return ""


def describe(eid):
    el = doc.GetElement(make_id(eid))
    if el is None:
        return {"id": eid, "exists": False}
    cat = el.Category.Name if el.Category is not None else ""
    d = {"id": eid, "exists": True, "name": txt(el.Name), "category": txt(cat),
         "kind": "none", "point": None, "rotation": None,
         "pinned": bool(el.Pinned), "groupId": 0, "hostId": 0, "hostCategory": "",
         "dependents": [], "levelId": 0, "isView": isinstance(el, DB.View),
         "viewSpecific": False}
    if el.GroupId is not None and el.GroupId != DB.ElementId.InvalidElementId:
        d["groupId"] = eid_int(el.GroupId)
    if el.LevelId is not None and el.LevelId != DB.ElementId.InvalidElementId:
        d["levelId"] = eid_int(el.LevelId)
    try:
        d["viewSpecific"] = el.OwnerViewId != DB.ElementId.InvalidElementId
    except Exception:
        pass
    loc = el.Location
    if isinstance(loc, DB.LocationPoint):
        d["kind"] = "point"
        d["point"] = xyz(loc.Point)
        try:
            d["rotation"] = norm_deg(loc.Rotation)
        except Exception:
            d["rotation"] = None  # not supported for groups, rooms, model text...
    elif isinstance(loc, DB.LocationCurve):
        c = loc.Curve
        d["kind"] = "curve"
        d["point"] = xyz(c.Evaluate(0.5, True))
        a, b = c.GetEndPoint(0), c.GetEndPoint(1)
        dx, dy = b.X - a.X, b.Y - a.Y
        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            d["rotation"] = norm_deg(math.atan2(dy, dx))
    if isinstance(el, DB.FamilyInstance):
        host = el.Host
        if host is not None and not isinstance(host, DB.Level):
            d["hostId"] = eid_int(host.Id)
            d["hostCategory"] = txt(host.Category.Name if host.Category is not None else "")
    try:
        dep_ids = el.GetDependentElements(DB.ElementClassFilter(DB.FamilyInstance))
    except Exception:
        dep_ids = []
    for did in dep_ids or []:
        if did == el.Id:
            continue
        dep = doc.GetElement(did)
        h = getattr(dep, "Host", None)
        if h is not None and h.Id == el.Id:
            d["dependents"].append(eid_int(did))
    return d


result = {"document": txt(doc.Title), "lengthUnit": length_unit(), "escaped": ESCAPE,
          "elements": [describe(i) for i in requested_ids()]}

# -*- coding: utf-8 -*-
"""am-modeling-helpers: measure how much of each floor lies in each room (read only).

Submit the full text with run_query. IronPython 2.7 and CPython 3 (no
f-strings). The script opens no transaction and changes nothing. The
solids it makes are in memory only.

Method (it worked in the field, issue #132; point sampling and pure Python
point-in-polygon did not): for each room, extrude the room outline from
z_below_ft under the boundary plane to z_above_ft over it. Find the floors
whose bounding box meets that box (a fast prefilter). Intersect each floor
solid with the room solid and add up the upward faces of the result.

Inputs:
  room_ids           1 to 20 room ids (required)
  floor_ids          optional: only these floors (at most 200)
  z_below_ft         default 3.0
  z_above_ft         default 3.0
  boundary_location  "finish" (default) or "center"
  time_budget_s      default 240 (the run_query limit is 300)

Result: {"payload": "<JSON text>"} with kind "floor-room-coverage-read":
  {complete, pending_room_ids, elapsed_s, z_below_ft, z_above_ft,
   rooms:  [{id, uid, number, name, level_id, area_sf, boundary_z_ft,
             status "read" or "excluded", reason}],
   floors: [{id, uid, type_id, type_name, level_id, level_name,
             is_structural, height_offset_ft, thickness_ft, top_area_sf,
             top_z_ft, bottom_z_ft, sloped, in_group, pinned}],
   pairs:  [{room_id, floor_id, overlap_sf, overlap_cf, status, error_type}]}
When complete is false, run again with pending_room_ids. Decode the
payload and pass the file to floor_coverage_plan.py.
"""
import json
import time

from pyrevit.api import DB
from System.Collections.Generic import List

try:
    INPUTS = inputs  # noqa: F821  (injected by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}

MAX_ROOMS = 20
MAX_FLOORS = 200
UP = 0.5  # a face whose normal Z is above this faces up


def eid(element_id):
    """ElementId -> int. Revit 2024+ has .Value; older years only .IntegerValue."""
    if hasattr(element_id, "Value"):
        return int(element_id.Value)
    return int(element_id.IntegerValue)


def make_id(value):
    try:
        from System import Int64
        return DB.ElementId(Int64(value))
    except Exception:
        return DB.ElementId(int(value))


def positive_ids(values, limit, label):
    if not isinstance(values, list) or not 1 <= len(values) <= limit:
        raise ValueError("Pass 1 to %d ids in inputs.%s." % (limit, label))
    ids = []
    for raw in values:
        text = str(raw).strip()
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("Ids must be positive whole numbers.")
        if int(text) not in ids:
            ids.append(int(text))
    return ids


def number(name, default, low, high):
    value = INPUTS.get(name, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("inputs.%s must be a number." % name)
    if not low <= value <= high:
        raise ValueError("inputs.%s must be between %s and %s." % (name, low, high))
    return value


def param(element, bip):
    try:
        return element.get_Parameter(bip)
    except Exception:
        return None


def text_of(element, bip):
    p = param(element, bip)
    if p is None:
        return None
    return p.AsString() or p.AsValueString()


def type_name(element):
    if element is None:
        return None
    name = text_of(element, DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    if name:
        return name
    try:
        return element.Name
    except Exception:
        return None


def solids_of(element):
    options = DB.Options()
    options.ComputeReferences = False
    options.DetailLevel = DB.ViewDetailLevel.Fine
    found = []

    def walk(geometry, depth):
        if geometry is None:
            return
        for item in geometry:
            if isinstance(item, DB.Solid):
                if item.Volume > 1e-9:
                    found.append(item)
            elif isinstance(item, DB.GeometryInstance) and depth < 3:
                walk(item.GetInstanceGeometry(), depth + 1)

    walk(element.get_Geometry(options), 0)
    return found


def face_up_z(face):
    if isinstance(face, DB.PlanarFace):
        return face.FaceNormal.Z
    box = face.GetBoundingBox()
    middle = DB.UV((box.Min.U + box.Max.U) / 2.0, (box.Min.V + box.Max.V) / 2.0)
    return face.ComputeNormal(middle).Z


def up_area(solid):
    """Area of the faces that point up, and whether any of them is sloped."""
    total = 0.0
    sloped = False
    for face in solid.Faces:
        try:
            z = face_up_z(face)
        except Exception:
            continue
        if z > UP:
            total += face.Area
            if z < 0.999:
                sloped = True
    return total, sloped


def floor_facts(document, floor, cache):
    fid = eid(floor.Id)
    if fid in cache:
        return cache[fid]
    floor_type = document.GetElement(floor.GetTypeId())
    level = document.GetElement(floor.LevelId)
    structural = param(floor, DB.BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
    offset = param(floor, DB.BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM)
    thickness = param(floor, DB.BuiltInParameter.FLOOR_ATTR_THICKNESS_PARAM)
    solids = solids_of(floor)
    top, sloped = 0.0, False
    for solid in solids:
        area, slope = up_area(solid)
        top += area
        sloped = sloped or slope
    box = floor.get_BoundingBox(None)
    facts = {
        "id": fid, "uid": floor.UniqueId,
        "type_id": eid(floor.GetTypeId()), "type_name": type_name(floor_type),
        "level_id": eid(floor.LevelId), "level_name": level.Name if level is not None else None,
        "is_structural": bool(structural is not None and structural.AsInteger() == 1),
        "height_offset_ft": float(offset.AsDouble()) if offset is not None else None,
        "thickness_ft": float(thickness.AsDouble()) if thickness is not None else None,
        "top_area_sf": top, "sloped": sloped,
        "top_z_ft": float(box.Max.Z) if box is not None else None,
        "bottom_z_ft": float(box.Min.Z) if box is not None else None,
        "in_group": eid(floor.GroupId) > 0, "pinned": bool(floor.Pinned),
    }
    cache[fid] = facts
    cache[("solids", fid)] = solids
    return facts


def room_prism(room, options, z_below, z_above):
    boundary = room.GetBoundarySegments(options)
    if boundary is None or boundary.Count == 0:
        raise ValueError("no_boundary")
    loops = List[DB.CurveLoop]()
    z = None
    xs, ys = [], []
    shift = None
    for segments in boundary:
        loop = DB.CurveLoop()
        for segment in segments:
            curve = segment.GetCurve()
            loop.Append(curve)
            for xyz in curve.Tessellate():
                xs.append(xyz.X)
                ys.append(xyz.Y)
                if z is None:
                    z = xyz.Z
        if loop.IsOpen():
            raise ValueError("open_boundary_loop")
        if shift is None:
            shift = DB.Transform.CreateTranslation(DB.XYZ(0, 0, -z_below))
        loops.Add(DB.CurveLoop.CreateViaTransform(loop, shift))
    prism = DB.GeometryCreationUtilities.CreateExtrusionGeometry(loops, DB.XYZ.BasisZ, z_below + z_above)
    outline = DB.Outline(DB.XYZ(min(xs), min(ys), z - z_below), DB.XYZ(max(xs), max(ys), z + z_above))
    return prism, outline, z


def read_coverage(document):
    room_ids = positive_ids(INPUTS.get("room_ids"), MAX_ROOMS, "room_ids")
    floor_filter = None
    if INPUTS.get("floor_ids") is not None:
        floor_filter = set(positive_ids(INPUTS.get("floor_ids"), MAX_FLOORS, "floor_ids"))
    z_below = number("z_below_ft", 3.0, 0.1, 50.0)
    z_above = number("z_above_ft", 3.0, 0.1, 50.0)
    budget = number("time_budget_s", 240.0, 10.0, 280.0)
    location = str(INPUTS.get("boundary_location") or "finish").lower()
    if location not in ("finish", "center"):
        raise ValueError("boundary_location must be finish or center.")
    options = DB.SpatialElementBoundaryOptions()
    options.SpatialElementBoundaryLocation = (DB.SpatialElementBoundaryLocation.Finish
                                              if location == "finish"
                                              else DB.SpatialElementBoundaryLocation.Center)
    started = time.time()
    rooms, pairs, cache, pending = [], [], {}, []
    for index, room_id in enumerate(room_ids):
        if time.time() - started > budget:
            pending = room_ids[index:]
            break
        room = document.GetElement(make_id(room_id))
        row = {"id": room_id, "status": "read"}
        rooms.append(row)
        if room is None or not isinstance(room, DB.Architecture.Room):
            row.update({"status": "excluded", "reason": "room_not_found"})
            continue
        row.update({"uid": room.UniqueId,
                    "number": text_of(room, DB.BuiltInParameter.ROOM_NUMBER),
                    "name": text_of(room, DB.BuiltInParameter.ROOM_NAME),
                    "level_id": eid(room.LevelId), "area_sf": float(room.Area)})
        if room.Location is None or room.Area <= 0:
            row.update({"status": "excluded", "reason": "unplaced_or_unenclosed_room"})
            continue
        try:
            prism, outline, z = room_prism(room, options, z_below, z_above)
        except Exception as exc:
            row.update({"status": "excluded", "reason": str(exc) if isinstance(exc, ValueError)
                        else "boundary_solid_failed", "error_type": type(exc).__name__})
            continue
        row["boundary_z_ft"] = float(z)
        collector = (DB.FilteredElementCollector(document)
                     .OfCategory(DB.BuiltInCategory.OST_Floors)
                     .WhereElementIsNotElementType()
                     .WherePasses(DB.BoundingBoxIntersectsFilter(outline)))
        stopped = False
        for floor in collector:
            fid = eid(floor.Id)
            if floor_filter is not None and fid not in floor_filter:
                continue
            if time.time() - started > budget:
                stopped = True
                break
            pair = {"room_id": room_id, "floor_id": fid, "overlap_sf": 0.0, "overlap_cf": 0.0, "status": "ok"}
            try:
                floor_facts(document, floor, cache)
                solids = cache[("solids", fid)]
                if not solids:
                    pair["status"] = "no_solid"
                for solid in solids:
                    common = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                        solid, prism, DB.BooleanOperationsType.Intersect)
                    if common is None or common.Volume <= 1e-9:
                        continue
                    area, _ = up_area(common)
                    pair["overlap_sf"] += area
                    pair["overlap_cf"] += common.Volume
            except Exception as exc:
                pair.update({"status": "boolean_failed", "error_type": type(exc).__name__})
            pairs.append(pair)
        if stopped:
            rooms.pop()
            pairs = [p for p in pairs if p["room_id"] != room_id]
            pending = room_ids[index:]
            break
    floors = [value for key, value in cache.items() if not isinstance(key, tuple)]
    floors.sort(key=lambda f: f["id"])
    return {
        "kind": "floor-room-coverage-read", "boundary_location": location,
        "z_below_ft": z_below, "z_above_ft": z_above,
        "complete": not pending, "pending_room_ids": pending,
        "elapsed_s": round(time.time() - started, 1),
        "rooms": rooms, "floors": floors, "pairs": pairs,
    }


if doc is None or doc.IsFamilyDocument:  # noqa: F821
    result = {"error": "no_project_document", "message": "Open a Revit project, not a family."}
else:
    try:
        result = {"payload": json.dumps(read_coverage(doc), ensure_ascii=True)}  # noqa: F821
    except ValueError as exc:
        result = {"error": "bad_inputs", "message": str(exc)}

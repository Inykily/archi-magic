# -*- coding: utf-8 -*-
"""am-modeling-helpers: read room outlines and location points (read only).

Submit the full text with run_query. IronPython 2.7 and CPython 3 (no
f-strings). The script opens no transaction and changes nothing.

Inputs (one of the first two):
  room_ids            1 to 500 room ids
  level_id            every room on this level (at most 500)
  boundary_location   "finish" (default, the Revit area face) or "center"

Result: {"payload": "<JSON text>"} with kind "room-shape-read":
  {kind, boundary_location, complete, pending_room_ids, truncated,
   rooms: [{id, uid, number, name, level_id, level_name, area_sf,
            perimeter_ft, location [x, y, z] or null,
            revit_point_in_room, status "read" or "excluded", reason,
            loops: [[[x, y], ...]], loop_sources: [{segments,
            linked_segments, categories, element_ids}]}]}
Coordinates are Revit internal feet. Curves are tessellated, so arcs are
polygons. Decode the payload and pass the file to room_shape_report.py.
"""
import json
import time

from pyrevit.api import DB

try:
    INPUTS = inputs  # noqa: F821  (injected by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}

MAX_ROOMS = 500
MAX_POINTS = 50000
TIME_BUDGET_S = 120.0


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


def param_text(element, bip):
    try:
        p = element.get_Parameter(bip)
        if p is None:
            return None
        return p.AsString() or p.AsValueString()
    except Exception:
        return None


def target_rooms(document):
    """Return (rooms, truncated)."""
    if INPUTS.get("room_ids") is not None:
        rooms = []
        for value in positive_ids(INPUTS.get("room_ids"), MAX_ROOMS, "room_ids"):
            element = document.GetElement(make_id(value))
            rooms.append((value, element))
        return rooms, False
    if INPUTS.get("level_id") is not None:
        level_id = positive_ids([INPUTS.get("level_id")], 1, "level_id")[0]
        collector = (DB.FilteredElementCollector(document)
                     .OfCategory(DB.BuiltInCategory.OST_Rooms)
                     .WhereElementIsNotElementType())
        rooms = [(eid(r.Id), r) for r in collector if eid(r.LevelId) == level_id]
        rooms.sort(key=lambda pair: pair[0])
        return rooms[:MAX_ROOMS], len(rooms) > MAX_ROOMS
    raise ValueError("Pass inputs.room_ids or inputs.level_id.")


def read_room(document, room_id, room, options, budget):
    if room is None or not isinstance(room, DB.Architecture.Room):
        return {"id": room_id, "status": "excluded", "reason": "room_not_found", "loops": []}
    row = {
        "id": room_id, "uid": room.UniqueId,
        "number": param_text(room, DB.BuiltInParameter.ROOM_NUMBER),
        "name": param_text(room, DB.BuiltInParameter.ROOM_NAME),
        "level_id": None, "level_name": None,
        "area_sf": float(room.Area), "perimeter_ft": float(room.Perimeter),
        "location": None, "revit_point_in_room": None,
        "status": "read", "loops": [], "loop_sources": [],
    }
    try:
        level = document.GetElement(room.LevelId)
        row["level_id"] = eid(room.LevelId)
        row["level_name"] = level.Name if level is not None else None
    except Exception:
        pass
    location = room.Location
    point = getattr(location, "Point", None) if location is not None else None
    if point is not None:
        row["location"] = [float(point.X), float(point.Y), float(point.Z)]
    if point is None or room.Area <= 0:
        row.update({"status": "excluded", "reason": "unplaced_or_unenclosed_room"})
        return row
    try:
        row["revit_point_in_room"] = bool(room.IsPointInRoom(DB.XYZ(point.X, point.Y, point.Z + 0.5)))
    except Exception:
        row["revit_point_in_room"] = None
    boundary = room.GetBoundarySegments(options)
    if boundary is None or boundary.Count == 0:
        row.update({"status": "excluded", "reason": "no_boundary"})
        return row
    for segments in boundary:
        points = []
        categories = set()
        sources = set()
        linked = 0
        for segment in segments:
            curve = segment.GetCurve()
            for xyz in list(curve.Tessellate())[:-1]:
                points.append([round(float(xyz.X), 6), round(float(xyz.Y), 6)])
            source = eid(segment.ElementId)
            if eid(segment.LinkElementId) > 0:
                linked += 1
                categories.add("linked model")
            elif source > 0:
                sources.add(source)
                element = document.GetElement(segment.ElementId)
                category = getattr(element, "Category", None) if element is not None else None
                if category is not None:
                    categories.add(category.Name)
        budget["points"] += len(points)
        row["loops"].append(points)
        row["loop_sources"].append({
            "segments": segments.Count, "linked_segments": linked,
            "categories": sorted(categories), "element_ids": sorted(sources)[:20],
        })
    return row


def read_shapes(document):
    rooms, truncated = target_rooms(document)
    options = DB.SpatialElementBoundaryOptions()
    location = str(INPUTS.get("boundary_location") or "finish").lower()
    if location not in ("finish", "center"):
        raise ValueError("boundary_location must be finish or center.")
    options.SpatialElementBoundaryLocation = (DB.SpatialElementBoundaryLocation.Finish
                                              if location == "finish"
                                              else DB.SpatialElementBoundaryLocation.Center)
    started = time.time()
    budget = {"points": 0}
    rows = []
    pending = []
    for index, (room_id, room) in enumerate(rooms):
        if time.time() - started > TIME_BUDGET_S or budget["points"] > MAX_POINTS:
            pending = [r[0] for r in rooms[index:]]
            break
        try:
            rows.append(read_room(document, room_id, room, options, budget))
        except Exception as exc:
            rows.append({"id": room_id, "status": "excluded", "reason": "read_failed",
                         "error_type": type(exc).__name__, "loops": []})
    return {
        "kind": "room-shape-read", "boundary_location": location,
        "complete": not pending, "pending_room_ids": pending, "truncated": truncated,
        "rooms": rows,
    }


if doc is None or doc.IsFamilyDocument:  # noqa: F821
    result = {"error": "no_project_document", "message": "Open a Revit project, not a family."}
else:
    try:
        result = {"payload": json.dumps(read_shapes(doc), ensure_ascii=True)}  # noqa: F821
    except ValueError as exc:
        result = {"error": "bad_inputs", "message": str(exc)}

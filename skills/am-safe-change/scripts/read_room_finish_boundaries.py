# -*- coding: utf-8 -*-
"""Inventory selected room boundaries in Revit 2026 via run_query only."""

import json
from pyrevit.api import DB
from System import Int64
from System.Collections.Generic import List


MAX_ROOMS = 20
MAX_SEGMENTS = 2000
TOLERANCE_FT = 1e-6


def ids_from(values):
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_ROOMS:
        raise ValueError("Pass 1 to 20 room IDs in inputs.room_ids.")
    ids = set()
    for raw in values:
        text = str(raw)
        if not text.isdigit():
            raise ValueError("Room IDs must be positive whole numbers.")
        value = int(text)
        if not 0 < value <= 9223372036854775807:
            raise ValueError("Room ID is outside the supported range.")
        ids.add(value)
    return sorted(ids)


def xyz(point):
    return [point.X, point.Y, point.Z]


def excluded(room_id, reason):
    return {"room_id": room_id, "status": "excluded", "reason": reason}


def inspect_room(room, room_id, options, remaining):
    if not isinstance(room, DB.Architecture.Room):
        return excluded(room_id, "room_not_found"), 0
    if room.Location is None or room.Area <= 0:
        return excluded(room_id, "unplaced_or_unenclosed_room"), 0
    if room.LevelId.Value <= 0:
        return excluded(room_id, "missing_room_level"), 0
    boundary = room.GetBoundarySegments(options)
    if boundary is None or boundary.Count == 0:
        return excluded(room_id, "no_closed_boundary"), 0
    count = sum(loop.Count for loop in boundary)
    if count > remaining:
        return excluded(room_id, "segment_budget_exceeded"), 0

    profiles = List[DB.CurveLoop]()
    plane_height = None
    facts = []
    try:
        for segments in boundary:
            if segments.Count == 0:
                return excluded(room_id, "empty_boundary_loop"), count
            loop_facts = []
            profile = DB.CurveLoop()
            profiles.Add(profile)
            curves = [segment.GetCurve() for segment in segments]
            if any(curve is None or not curve.IsBound for curve in curves):
                return excluded(room_id, "unsupported_boundary_curve"), count
            starts = [curve.GetEndPoint(0) for curve in curves]
            ends = [curve.GetEndPoint(1) for curve in curves]
            if any(ends[i].DistanceTo(starts[(i + 1) % len(curves)]) > TOLERANCE_FT
                   for i in range(len(curves))):
                return excluded(room_id, "open_boundary_loop"), count
            for segment, curve, start, end in zip(segments, curves, starts, ends):
                profile.Append(curve)
                loop_facts.append({
                    "start_ft": xyz(start), "end_ft": xyz(end),
                    "curve_type": curve.GetType().Name,
                    "source_id": int(segment.ElementId.Value),
                    "linked_source_id": int(segment.LinkElementId.Value),
                })
            if not profile.HasPlane():
                return excluded(room_id, "nonplanar_boundary_loop"), count
            plane = profile.GetPlane()
            if abs(abs(plane.Normal.Z) - 1.0) > 1e-9:
                return excluded(room_id, "nonhorizontal_boundary_loop"), count
            if plane_height is not None and abs(plane.Origin.Z - plane_height) > TOLERANCE_FT:
                return excluded(room_id, "boundary_loops_on_different_planes"), count
            plane_height = plane.Origin.Z
            facts.append(loop_facts)
        if not DB.BoundaryValidation.IsValidHorizontalBoundary(profiles):
            return excluded(room_id, "invalid_boundary_topology"), count
        return {"room_id": room_id, "room_uid": room.UniqueId, "level_id": int(room.LevelId.Value),
                "status": "boundary_verified", "boundary_loops": facts}, count
    except Exception as exc:
        row = excluded(room_id, "boundary_read_failed")
        row["error_type"] = type(exc).__name__
        return row, count
    finally:
        for profile in profiles:
            profile.Dispose()


def read_boundaries(document, room_ids):
    rows = []
    remaining = MAX_SEGMENTS
    options = DB.SpatialElementBoundaryOptions()
    options.SpatialElementBoundaryLocation = DB.SpatialElementBoundaryLocation.Finish
    try:
        for room_id in room_ids:
            try:
                room = document.GetElement(DB.ElementId(Int64(room_id)))
                row, used = inspect_room(room, room_id, options, remaining)
                remaining -= used
            except Exception as exc:
                row = excluded(room_id, "boundary_read_failed")
                row["error_type"] = type(exc).__name__
            rows.append(row)
    finally:
        options.Dispose()
    return {
        "status": "reported" if all(row["status"] == "boundary_verified" for row in rows) else "incomplete",
        "rooms": rows,
        "boundary_location": "finish",
        "placement_available": False,
    }


if doc is None or doc.IsFamilyDocument:
    result = {"error": "Open a Revit project before reading room boundaries."}
else:
    report = read_boundaries(doc, ids_from(inputs.get("room_ids")))
    result = {"payload": json.dumps(report, ensure_ascii=True)}

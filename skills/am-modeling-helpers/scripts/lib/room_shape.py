# -*- coding: utf-8 -*-
"""Find broken room shapes before you model finishes from a room boundary.

Pure Python (CPython 3 and IronPython 2.7). Input is the report of
read_room_shapes.py. Each room has its boundary loops as plan points in
feet, its location point, and the area and perimeter that Revit reports.

A field case (issue #132): a room was a ring about 3 in wide. Its outer
loop was a linked building outline, its hole was bounded by a roof floor,
and its location point was outside its own boundary. A finish floor drawn
from that boundary is a 3 in ring. These checks catch that case:

- point_outside: the location point is not inside the boundary (even-odd
  rule over all loops, so a point in a hole is outside).
- narrow / ring: the mean width 2 * area / perimeter is below a limit. A
  strip of width w and a ring of width w both give about w.
- tiny, no_area, no_boundary, no_location_point: nothing safe to model.
- large_hole, area_mismatch, revit_point_check_differs: warnings to review.
"""
from __future__ import division

import math

DEFAULT_RULES = {
    "min_width_ft": 1.0,      # mean width below 12 in is a sliver or a ring
    "min_area_sf": 2.0,       # smaller rooms are not real rooms
    "area_tolerance": 0.05,   # computed area vs Revit area
    "large_hole_ratio": 0.5,  # hole area / outer area
    "boundary_tolerance_ft": 1e-4,
}

BLOCK = "block"
WARN = "warn"


def signed_area(points):
    total = 0.0
    count = len(points)
    for i in range(count):
        x1, y1 = points[i][0], points[i][1]
        x2, y2 = points[(i + 1) % count][0], points[(i + 1) % count][1]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def perimeter(points):
    count = len(points)
    return sum(math.hypot(points[(i + 1) % count][0] - points[i][0],
                          points[(i + 1) % count][1] - points[i][1])
               for i in range(count))


def distance_to_segment(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 0.0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def inside_loop(p, points):
    """Ray casting. Points on the edge can go either way; check them first."""
    x, y = p[0], p[1]
    inside = False
    count = len(points)
    j = count - 1
    for i in range(count):
        xi, yi = points[i][0], points[i][1]
        xj, yj = points[j][0], points[j][1]
        if (yi > y) != (yj > y):
            cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < cross:
                inside = not inside
        j = i
    return inside


def locate_point(p, loops, tolerance=1e-4):
    """'inside', 'outside' or 'on_boundary' by the even-odd rule over all loops."""
    for points in loops:
        count = len(points)
        for i in range(count):
            if distance_to_segment(p, points[i], points[(i + 1) % count]) <= tolerance:
                return "on_boundary"
    hits = sum(1 for points in loops if inside_loop(p, points))
    return "inside" if hits % 2 == 1 else "outside"


def clean_loops(loops):
    """Drop loops with fewer than 3 points and a repeated closing point."""
    result = []
    for points in loops or []:
        pts = [(float(q[0]), float(q[1])) for q in points]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) >= 3:
            result.append(pts)
    return result


def shape_metrics(loops):
    """Area, perimeter, holes and mean width of a set of boundary loops.

    Loop order does not tell which loop is a hole. A loop inside an odd
    number of other loops is a hole.
    """
    loops = clean_loops(loops)
    areas = [abs(signed_area(pts)) for pts in loops]
    depths = []
    for i, pts in enumerate(loops):
        probe = pts[0]
        depths.append(sum(1 for j, other in enumerate(loops)
                          if j != i and inside_loop(probe, other)))
    outer = sum(a for a, d in zip(areas, depths) if d % 2 == 0)
    holes = sum(a for a, d in zip(areas, depths) if d % 2 == 1)
    length = sum(perimeter(pts) for pts in loops)
    net = outer - holes
    return {
        "loop_count": len(loops),
        "hole_count": sum(1 for d in depths if d % 2 == 1),
        "outer_area_sf": outer,
        "hole_area_sf": holes,
        "net_area_sf": net,
        "perimeter_ft": length,
        "mean_width_ft": (2.0 * net / length) if length > 0 else 0.0,
    }


def _flag(code, severity, text):
    return {"code": code, "severity": severity, "text": text}


def check_room(room, rules=None):
    """Return one report row with flags and a verdict: ok, warn or block."""
    r = dict(DEFAULT_RULES)
    r.update(rules or {})
    row = {
        "id": room.get("id"),
        "number": room.get("number"),
        "name": room.get("name"),
        "level_name": room.get("level_name"),
        "revit_area_sf": room.get("area_sf"),
        "flags": [],
    }
    flags = row["flags"]
    if room.get("status") == "excluded":
        flags.append(_flag("no_boundary", BLOCK, "Revit gave no usable boundary (%s)." % room.get("reason")))
        row["verdict"] = BLOCK
        return row

    loops = clean_loops(room.get("loops"))
    metrics = shape_metrics(loops)
    row.update({
        "computed_area_sf": round(metrics["net_area_sf"], 3),
        "perimeter_ft": round(metrics["perimeter_ft"], 3),
        "mean_width_in": round(metrics["mean_width_ft"] * 12.0, 2),
        "hole_count": metrics["hole_count"],
    })
    if not loops or metrics["net_area_sf"] <= 0:
        flags.append(_flag("no_area", BLOCK, "The boundary encloses no area."))
    else:
        location = room.get("location")
        if not location:
            flags.append(_flag("no_location_point", BLOCK, "The room has no location point."))
        else:
            where = locate_point(location, loops, r["boundary_tolerance_ft"])
            row["location_point"] = where
            if where != "inside":
                flags.append(_flag("point_outside", BLOCK,
                                   "The location point is %s its own boundary." % where.replace("_", " ")))
            revit_check = room.get("revit_point_in_room")
            if revit_check is not None and bool(revit_check) != (where == "inside"):
                flags.append(_flag("revit_point_check_differs", WARN,
                                   "Revit's own point-in-room check gives a different answer."))
        if metrics["net_area_sf"] < r["min_area_sf"]:
            flags.append(_flag("tiny", BLOCK, "The area is %.2f sf." % metrics["net_area_sf"]))
        if metrics["mean_width_ft"] < r["min_width_ft"]:
            if metrics["hole_count"]:
                flags.append(_flag("ring", BLOCK,
                                   "The room is a ring about %.1f in wide around a hole." % (metrics["mean_width_ft"] * 12.0)))
            else:
                flags.append(_flag("narrow", BLOCK,
                                   "The room is a strip about %.1f in wide." % (metrics["mean_width_ft"] * 12.0)))
        if metrics["outer_area_sf"] > 0 and metrics["hole_area_sf"] / metrics["outer_area_sf"] >= r["large_hole_ratio"]:
            flags.append(_flag("large_hole", WARN, "Holes take %.0f%% of the outer outline." % (
                100.0 * metrics["hole_area_sf"] / metrics["outer_area_sf"])))
        revit_area = room.get("area_sf") or 0.0
        if revit_area > 0 and abs(metrics["net_area_sf"] - revit_area) > r["area_tolerance"] * revit_area:
            flags.append(_flag("area_mismatch", WARN,
                               "The boundary gives %.1f sf. Revit reports %.1f sf." % (metrics["net_area_sf"], revit_area)))
    severities = set(f["severity"] for f in flags)
    row["verdict"] = BLOCK if BLOCK in severities else (WARN if WARN in severities else "ok")
    sources = room.get("loop_sources") or []
    if sources and row["verdict"] != "ok":
        row["loop_sources"] = sources
    return row


def report(read, rules=None):
    rows = [check_room(room, rules) for room in read.get("rooms", [])]
    counts = {"rooms": len(rows), "ok": 0, "warn": 0, "block": 0}
    for row in rows:
        counts[row["verdict"]] += 1
    r = dict(DEFAULT_RULES)
    r.update(rules or {})
    notes = ["%d of %d rooms are not safe to model finishes from." % (counts["block"], counts["rooms"])]
    if not read.get("complete", True):
        notes.append("The read is incomplete. Pending rooms: %s." % ", ".join(
            str(i) for i in read.get("pending_room_ids", [])))
    return {"kind": "room-shape-report", "rules": r, "counts": counts,
            "complete": bool(read.get("complete", True)), "notes": notes, "rooms": rows}

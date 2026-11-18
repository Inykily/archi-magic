# -*- coding: utf-8 -*-
"""Pure helpers for new detail sections from a plan markup (issue #257).

- look_from_bar_side: the look direction of a section mark drawn on a
  plan, from the side of its thick bar (the head flag). Reviewers often
  draw marks mirrored against the head/tail rule, so the bar side is the
  rule, not the order of the two ends.
- detail_box: the BoundingBoxXYZ frame and extents for
  ViewSection.CreateDetail. CreateDetail reads BasisZ as the look-into
  direction. The new view's ViewDirection (towards the viewer) is -look.
- view_direction_ok: the check after CreateDetail.
- find_duplicates: an existing section marker near a new cut. The user
  rule from the field report: never cut the same spot twice.

All lengths are Revit internal feet, in plan coordinates (x, y).
Pure computation. Runs under CPython 3 and IronPython 2.7: no f-strings,
no type annotations, no nonlocal. No Revit imports.
"""

import math

UP = [0.0, 0.0, 1.0]


def _unit2(v):
    n = math.hypot(v[0], v[1])
    if n < 1e-9:
        raise ValueError("A cut line needs two different points.")
    return [v[0] / n, v[1] / n]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def look_from_bar_side(start, end, bar_side):
    """Unit look direction (x, y, 0): perpendicular to the cut line, towards
    the side of the point bar_side (any point on the thick bar or the arrow)."""
    d = _unit2([end[0] - start[0], end[1] - start[1]])
    normal = [-d[1], d[0]]
    mid = [(start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0]
    side = (bar_side[0] - mid[0]) * normal[0] + (bar_side[1] - mid[1]) * normal[1]
    if abs(side) < 1e-9:
        raise ValueError("The bar side point is on the cut line. Pick a point on the bar.")
    if side < 0:
        normal = [-normal[0], -normal[1]]
    return [normal[0], normal[1], 0.0]


def detail_box(start, end, look, bottom_z, top_z, depth, padding=0.0):
    """Frame and extents for CreateDetail for one cut line.

    The box is right-handed (BoundingBoxXYZ needs it): BasisZ = look (into
    the model), BasisY = up, BasisX = up x look. The origin is on the cut
    line, so the cut plane is local z = 0 and the far clip is z = depth.
    bottom_z and top_z are absolute elevations (ft) of the view's bottom
    and top edge. padding (ft) widens the crop on each side of the line.
    """
    if top_z <= bottom_z:
        raise ValueError("top_z must be above bottom_z.")
    if depth <= 0:
        raise ValueError("depth must be more than 0.")
    d = _unit2([end[0] - start[0], end[1] - start[1]])
    lk = _unit2(look[:2])
    if abs(d[0] * lk[0] + d[1] * lk[1]) > 1e-6:
        raise ValueError("The look direction must be perpendicular to the cut line.")
    look3 = [lk[0], lk[1], 0.0]
    half = math.hypot(end[0] - start[0], end[1] - start[1]) / 2.0 + padding
    origin = [(start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0, 0.0]
    return {"origin": origin, "basis_x": _cross(UP, look3), "basis_y": list(UP),
            "basis_z": look3, "min": [-half, float(bottom_z), 0.0],
            "max": [half, float(top_z), float(depth)]}


def view_direction_ok(view_direction, look, tolerance=1e-6):
    """True when a new view's ViewDirection (towards the viewer) is -look."""
    n = math.sqrt(sum(c * c for c in view_direction))
    if n < 1e-12:
        return False
    dot = -sum(a * b for a, b in zip(view_direction, look)) / n
    return dot >= 1.0 - tolerance


def _point_segment_distance(p, a, b):
    ab = [b[0] - a[0], b[1] - a[1]]
    length2 = ab[0] * ab[0] + ab[1] * ab[1]
    if length2 < 1e-18:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / length2
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (a[0] + t * ab[0]), p[1] - (a[1] + t * ab[1]))


def _angle_between_lines(a1, a2, b1, b2):
    """Angle in degrees between two lines, 0 to 90 (direction sign ignored)."""
    da = _unit2([a2[0] - a1[0], a2[1] - a1[1]])
    db = _unit2([b2[0] - b1[0], b2[1] - b1[1]])
    c = min(1.0, abs(da[0] * db[0] + da[1] * db[1]))
    return math.degrees(math.acos(c))


def nearest_marker(cut, existing):
    """(marker, distance ft, angle deg) of the existing marker nearest to the
    middle of the cut, or (None, None, None)."""
    mid = [(cut["start"][0] + cut["end"][0]) / 2.0, (cut["start"][1] + cut["end"][1]) / 2.0]
    best = (None, None, None)
    for m in existing or []:
        dist = _point_segment_distance(mid, m["start"], m["end"])
        if best[1] is None or dist < best[1]:
            best = (m, dist, _angle_between_lines(cut["start"], cut["end"], m["start"], m["end"]))
    return best


def find_duplicates(cuts, existing, tolerance=1.0, max_angle=10.0):
    """One row per cut: the cut, the nearest existing marker, and whether
    the cut duplicates it (closer than tolerance ft and within max_angle
    degrees of parallel). Two new cuts that duplicate each other are also
    found: the later one is the duplicate."""
    rows = []
    accepted = []
    for cut in cuts:
        marker, dist, angle = nearest_marker(cut, existing)
        dup = marker is not None and dist <= tolerance and angle <= max_angle
        dup_of = (marker.get("name") or marker.get("id")) if dup else None
        if not dup:
            other, d2, a2 = nearest_marker(cut, accepted)
            if other is not None and d2 <= tolerance and a2 <= max_angle:
                dup, dup_of, dist, angle = True, "new cut %s" % other.get("name"), d2, a2
        rows.append({"name": cut.get("name"), "duplicate": dup, "duplicate_of": dup_of,
                     "nearest": (marker.get("name") or marker.get("id")) if marker else None,
                     "distance": dist, "angle": angle})
        if not dup:
            accepted.append(cut)
    return rows


def markers_at_level(markers, z, margin=0.0):
    """Existing markers whose vertical extent includes elevation z (ft)."""
    out = []
    for m in markers or []:
        lo, hi = m.get("z_min"), m.get("z_max")
        if lo is None or hi is None or (lo - margin <= z <= hi + margin):
            out.append(m)
    return out

# -*- coding: utf-8 -*-
"""EXECUTE step for the element-transforms recipe (run_modify / --mode=dry_run|modify).

inputs: {"preview_path": "C:/.../x.preview.json"}   (forward slashes are fine)
    or  {"preview": {...preview dict...}}

For each preview step, in ONE transaction (the user's Keep/Discard is all-or-nothing):
    1. ElementTransformUtils.RotateElement about Line.CreateBound(pivot, pivot + XYZ.BasisZ)
       by radians(rotateZ)   (only when rotateZ != 0), then
    2. ElementTransformUtils.MoveElement by XYZ(dx, dy, dz)   (only when the move is not 0).
Same order as scripts/lib/transforms.py.

Before it changes anything it checks every step's element still has the
preview's "before" location (within 1e-6 ft) and rotation (within 1e-4 deg).
If not, it stops with "Model changed since the preview" and changes nothing.

result = {"rows": [{"id", "point", "rotation", "status"}], "steps_applied": n,
          "partial": true (only the moved elements are listed), "escaped": bool}
A dry run returns the same result and Revit rolls everything back.
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import io
import json
import math
import sys

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"
POINT_TOL = 1e-6
ANGLE_TOL = 1e-4


def make_id(i):
    try:
        import System
        return DB.ElementId(System.Int64(i))  # Revit 2024+ (2026 has only Int64)
    except Exception:
        return DB.ElementId(int(i))


def norm_deg(rad):
    d = math.degrees(rad) % 360.0
    return 0.0 if abs(d) < 1e-12 or d >= 360.0 - 1e-12 else d


def angle_diff(a, b):
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def state(el):
    """(point, rotation) the same way read_elements.py measures it."""
    loc = el.Location
    if isinstance(loc, DB.LocationPoint):
        p = loc.Point
        try:
            r = norm_deg(loc.Rotation)
        except Exception:
            r = None
        return [float(p.X), float(p.Y), float(p.Z)], r
    if isinstance(loc, DB.LocationCurve):
        c = loc.Curve
        m = c.Evaluate(0.5, True)
        a, b = c.GetEndPoint(0), c.GetEndPoint(1)
        dx, dy = b.X - a.X, b.Y - a.Y
        r = norm_deg(math.atan2(dy, dx)) if (abs(dx) > 1e-9 or abs(dy) > 1e-9) else None
        return [float(m.X), float(m.Y), float(m.Z)], r
    return None, None


def load_preview():
    if inputs.get("preview"):
        return inputs["preview"]
    path = inputs.get("preview_path")
    if not path:
        raise ValueError("inputs needs preview_path or preview")
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.loads(f.read())


preview = load_preview()
if preview.get("kind") != "change-preview":
    raise ValueError("Not a change-preview file.")
if preview.get("blocked"):
    raise ValueError("The preview is BLOCKED. Decide its blocking warnings first.")
steps = preview.get("steps") or []
if not steps or "expectAfter" not in steps[0]:
    raise ValueError("The preview has no element-transform steps. Nothing to apply.")

# Stale-state guard.
elements = {}
stale = []
for st in steps:
    eid = int(st["id"])
    el = doc.GetElement(make_id(eid))
    if el is None:
        stale.append("element %s no longer exists" % eid)
        continue
    elements[eid] = el
    p, r = state(el)
    want_p, want_r = st["expect"]["point"], st["expect"].get("rotation")
    if p is None or any(abs(p[i] - want_p[i]) > POINT_TOL for i in range(3)):
        stale.append("element %s location is %s, preview says %s" % (eid, p, want_p))
    elif want_r is not None and (r is None or angle_diff(r, want_r) > ANGLE_TOL):
        stale.append("element %s rotation is %s, preview says %s" % (eid, r, want_r))
    if el.Pinned:
        stale.append("element %s is pinned" % eid)
if stale:
    raise ValueError("Model changed since the preview. Read and preview again. " + "; ".join(stale[:10]))

t = DB.Transaction(doc, preview.get("title") or "Move or rotate elements")
t.Start()
done = 0
try:
    for st in steps:
        eid = int(st["id"])
        rz = float(st.get("rotateZ") or 0.0)
        if rz != 0.0:
            pv = st["pivot"]
            base = DB.XYZ(pv[0], pv[1], pv[2])
            axis = DB.Line.CreateBound(base, base + DB.XYZ.BasisZ)
            DB.ElementTransformUtils.RotateElement(doc, elements[eid].Id, axis, math.radians(rz))
        mv = st.get("move") or [0.0, 0.0, 0.0]
        if any(v != 0.0 for v in mv):
            DB.ElementTransformUtils.MoveElement(doc, elements[eid].Id, DB.XYZ(mv[0], mv[1], mv[2]))
        done += 1
    t.Commit()
except Exception:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    raise

rows = []
for st in steps:
    eid = int(st["id"])
    el = doc.GetElement(make_id(eid))
    p, r = state(el) if el is not None else (None, None)
    rows.append({"id": eid, "point": p, "rotation": r,
                 "status": "done" if el is not None else "missing after apply"})

result = {"rows": rows, "steps_applied": done, "partial": True, "escaped": ESCAPE}

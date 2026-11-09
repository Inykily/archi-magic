# -*- coding: utf-8 -*-
# Place floor drains (PLBG-FLOOR DRAIN-2D) in toilet rooms on one floor plan.
# See "Placement rules" in SKILL.md. Run with run_modify (dry_run first).
# Needs `inputs`:
#   view_id      int   target floor plan (a ViewPlan); its level is used
#   family_name  str   optional, default "PLBG-FLOOR DRAIN-2D"
#   type_name    str   optional, default "Floor Drain-2D"
#   room_keys    list  optional, room-name parts that get a drain (default TOILET, RESTROOM, WC)
#   room_ids     list  optional, only these room ids (for a test on a few rooms)
#   grid_offsets dict  optional, {"<floor id>": [ox, oy]}: the tile grid of that floor element has
#                      X lines at x = ox + n*gx and Y lines at y = oy + m*gy (internal feet).
#                      Measure them with the procedure in SKILL.md. A floor with a tile pattern but
#                      no entry is placed at the exact target and listed in NEEDS_GRID_MEASURE.
#   target_past  float optional, ft past the bowl front (default 1.5 = 18")
#   min_past     float optional, ft past the bowl front, minimum after snap (default 1.0 = 12")
#   wall_clear   float optional, ft from the room boundary (default 1.0)
#   points       dict  optional, {"<room id>": [x, y]}: approved aisle points in selected rooms
#   resnap       bool  optional, true = move only approved drains onto measured grids
#   resnap_drain_ids list required with resnap, drain ids from the approved placement's "created" map
# Python 2.7 syntax (IronPython).
from pyrevit.api import DB
import math, System

def EID(n): return DB.ElementId(System.Int64(int(n)))
def asc(x):
    try: return unicode(x).encode("ascii", "replace")
    except: return "?"

view = doc.GetElement(EID(inputs["view_id"]))
level = view.GenLevel
phase = doc.GetElement(view.get_Parameter(DB.BuiltInParameter.VIEW_PHASE).AsElementId())

if "moves" in inputs or "ignore_existing" in inputs:
    raise ValueError("This skill does not support arbitrary moves or bypassing existing drains.")
else:
    FAM = inputs.get("family_name", "PLBG-FLOOR DRAIN-2D")
    TYP = inputs.get("type_name", "Floor Drain-2D")
    KEYS = tuple(k.upper() for k in inputs.get("room_keys", ["TOILET", "RESTROOM", "WC"]))
    ONLY = set(int(x) for x in inputs.get("room_ids", []))
    GRID = dict((str(k), v) for k, v in (inputs.get("grid_offsets") or {}).items())
    PAST = float(inputs.get("target_past", 1.5))
    MINP = float(inputs.get("min_past", 1.0))
    CLR = float(inputs.get("wall_clear", 1.0))
    RESNAP = bool(inputs.get("resnap", False))
    RESNAP_IDS = set(int(x) for x in inputs.get("resnap_drain_ids", []))
    POINTS = dict((int(k), v) for k, v in (inputs.get("points") or {}).items())
    if RESNAP and not RESNAP_IDS:
        raise ValueError("Resnap requires resnap_drain_ids from the approved placement.")
    if RESNAP and POINTS:
        raise ValueError("Resnap does not place new drains; omit points.")

    sym = None
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        if s.Family.Name == FAM and DB.Element.Name.GetValue(s) == TYP: sym = s; break
    if sym is None: raise Exception("Family type not loaded: %s : %s" % (FAM, TYP))

    fixtures = [f for f in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_PlumbingFixtures)
                .WhereElementIsNotElementType() if isinstance(f, DB.FamilyInstance) and isinstance(f.Location, DB.LocationPoint)]
    def is_drain(f):
        name = (f.Symbol.Family.Name + " " + DB.Element.Name.GetValue(f.Symbol)).upper()
        return f.Symbol.Id == sym.Id or "FLOOR DRAIN" in name or "FLOOR-DRAIN" in name
    drains = [f for f in fixtures if f.LevelId == level.Id and is_drain(f)]
    def is_wc(f):
        n = (f.Symbol.Family.Name + " " + DB.Element.Name.GetValue(f.Symbol)).upper()
        return ("TOILET" in n or "WATER CLOSET" in n) and f.Symbol.Id != sym.Id
    def is_shower(f):
        return "SHOWER" in (f.Symbol.Family.Name + " " + DB.Element.Name.GetValue(f.Symbol)).upper()
    wcs_all = [f for f in fixtures if is_wc(f)]
    doors = [d for d in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Doors)
             .WhereElementIsNotElementType() if isinstance(d, DB.FamilyInstance) and isinstance(d.Location, DB.LocationPoint)]
    floors = list(DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Floor))

    def near(f, bb, tol):
        p = f.Location.Point
        return (bb.Min.X - tol <= p.X <= bb.Max.X + tol and bb.Min.Y - tol <= p.Y <= bb.Max.Y + tol
                and abs(p.Z - bb.Min.Z) < 4)

    def on_top_face(f, x, y, ztop):
        # A bounding box is not enough: a big L-shaped floor covers rooms it does not touch.
        for ref in DB.HostObjectUtils.GetTopFaces(f):
            face = f.GetGeometryObjectFromReference(ref)
            res = face.Project(DB.XYZ(x, y, ztop)) if face else None
            if res and abs(res.XYZPoint.X - x) < 0.01 and abs(res.XYZPoint.Y - y) < 0.01:
                return True
        return False

    def tile_grid(x, y, z):
        """Top floor under (x, y) and its orthogonal MODEL tile pattern (gx, gy), if any."""
        best = None
        for f in floors:
            bb = f.get_BoundingBox(None)
            if bb is None or not (bb.Min.X <= x <= bb.Max.X and bb.Min.Y <= y <= bb.Max.Y and bb.Max.Z > z - 2 and bb.Min.Z < z + 1):
                continue
            if not on_top_face(f, x, y, bb.Max.Z): continue
            cs = doc.GetElement(f.GetTypeId()).GetCompoundStructure()
            if cs is None or cs.LayerCount == 0: continue
            m = doc.GetElement(cs.GetLayers()[0].MaterialId)
            fp = doc.GetElement(m.SurfaceForegroundPatternId) if m else None
            rec = {"floor_id": f.Id.Value, "floor_type": asc(DB.Element.Name.GetValue(doc.GetElement(f.GetTypeId()))), "top": bb.Max.Z}
            if fp:
                pat = fp.GetFillPattern()
                rec["pattern"] = asc(fp.Name)
                gx = gy = None
                if pat.Target == DB.FillPatternTarget.Model:
                    for g in pat.GetFillGrids():
                        if len(list(g.GetSegments())) > 0: gx = gy = None; break   # dashed: not a simple tile
                        a = g.Angle % math.pi
                        if abs(a) < 0.01 or abs(a - math.pi) < 0.01: gy = g.Offset
                        elif abs(a - math.pi / 2) < 0.01: gx = g.Offset
                rec["gx"], rec["gy"] = gx, gy
            if best is None or rec["top"] > best["top"] + 0.001 or (abs(rec["top"] - best["top"]) <= 0.001 and rec.get("gx") and not best.get("gx")):
                best = rec
        return best

    report, plan, needs = [], [], {}
    used_points = set()
    boundary_options = DB.SpatialElementBoundaryOptions()
    for r in DB.FilteredElementCollector(doc, view.Id).OfCategory(DB.BuiltInCategory.OST_Rooms):
        if r.Area <= 0 or r.LevelId != level.Id: continue
        if ONLY and r.Id.Value not in ONLY: continue
        name = (r.get_Parameter(DB.BuiltInParameter.ROOM_NAME).AsString() or "").upper()
        if not ONLY and not any(k in name for k in KEYS): continue
        bb = r.get_BoundingBox(None); z = bb.Min.Z + 1.0
        x0, y0, x1, y1 = bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y
        room_id = r.Id.Value
        rep = {"room": r.Number, "name": asc(name), "room_id": room_id}
        point = POINTS.get(room_id)
        if room_id in POINTS:
            used_points.add(room_id)
        inroom = [dd for dd in drains if r.IsPointInRoom(DB.XYZ(dd.Location.Point.X, dd.Location.Point.Y, z))]
        if RESNAP:
            selected = [d for d in inroom if d.Id.Value in RESNAP_IDS and d.Symbol.Id == sym.Id]
            if not selected:
                continue
            if len(inroom) != 1:
                rep["skip"] = "ASK: resnap room has more than one drain"; report.append(rep); continue
            rep["drain_id"] = selected[0].Id.Value
        elif inroom:
            rep["skip"] = "already has a drain"; report.append(rep); continue
        if any(is_shower(f) and near(f, bb, 0.3) for f in fixtures):
            rep["skip"] = "ASK: room has a shower; drain goes in the shower (not automated)"; report.append(rep); continue
        curves = [segment.GetCurve() for loop in (r.GetBoundarySegments(boundary_options) or []) for segment in loop]
        boundaries = [(curve, curve.GetEndPoint(0).Z) for curve in curves]
        def clear_room(x, y):
            return (r.IsPointInRoom(DB.XYZ(x, y, z)) and bool(boundaries)
                    and all(curve.Distance(DB.XYZ(x, y, height)) >= CLR for curve, height in boundaries))
        if room_id in POINTS:
            x, y = (float(v) for v in point)
            if any(math.isnan(v) or math.isinf(v) for v in (x, y)) or not clear_room(x, y):
                rep["skip"] = "ASK: approved point fails the selected room's boundary clearance"; report.append(rep); continue
            rep.update({"mode": "user point", "xy": [round(x, 3), round(y, 3)]})
            report.append(rep); plan.append((str(room_id), x, y, None))
            continue
        wcs = [f for f in wcs_all if near(f, bb, 0.75)]
        if len(wcs) > 1: wcs = [f for f in wcs if near(f, bb, 0.3)]    # back-to-back WCs on a shared wall
        if len(wcs) != 1:
            rep["skip"] = "ASK: found %d WCs" % len(wcs); report.append(rep); continue
        wc = wcs[0]; p = wc.Location.Point
        d = {"W": abs(p.X - x0), "E": abs(p.X - x1), "S": abs(p.Y - y0), "N": abs(p.Y - y1)}
        side = min(d, key=d.get)
        dx, dy = {"W": (1, 0), "E": (-1, 0), "S": (0, 1), "N": (0, -1)}[side]
        wall = {"W": x0, "E": x1, "S": y0, "N": y1}[side]
        wbb = wc.get_BoundingBox(None)          # bowl length = how far the WC sticks out of the wall
        if dx: bowl = (wbb.Max.X - wall) if dx > 0 else (wall - wbb.Min.X)
        else:  bowl = (wbb.Max.Y - wall) if dy > 0 else (wall - wbb.Min.Y)
        bowl = bowl if 1.0 < bowl < 3.5 else 2.1
        tx, ty = p.X, p.Y
        if dx: tx = wall + dx * (bowl + PAST)
        if dy: ty = wall + dy * (bowl + PAST)
        boxes = []                               # door swing, as a box on both sides (conservative)
        for dr in doors:
            dp = dr.Location.Point
            if abs(dp.Z - bb.Min.Z) > 3: continue
            tr = dr.get_ToRoom(phase); fr = dr.get_FromRoom(phase)
            hit = (tr and tr.Id == r.Id) or (fr and fr.Id == r.Id)
            if not hit and not (x0 - 1 <= dp.X <= x1 + 1 and y0 - 1 <= dp.Y <= y1 + 1): continue
            wp = dr.Symbol.get_Parameter(DB.BuiltInParameter.DOOR_WIDTH) or dr.get_Parameter(DB.BuiltInParameter.DOOR_WIDTH)
            w = wp.AsDouble() if wp else 3.0
            if abs(dr.HandOrientation.X) > 0.5:
                boxes.append((dp.X - w / 2 - 0.25, dp.Y - w - 0.5, dp.X + w / 2 + 0.25, dp.Y + w + 0.5))
            else:
                boxes.append((dp.X - w - 0.5, dp.Y - w / 2 - 0.25, dp.X + w + 0.5, dp.Y + w / 2 + 0.25))
        def ok(cx, cy):
            if not clear_room(cx, cy): return None
            past = dx * (cx - wall) + dy * (cy - wall) - bowl
            if past < MINP - 1e-6: return None
            if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes): return None
            return past
        g = tile_grid(tx, ty, bb.Min.Z)
        rep.update({"wc_id": wc.Id.Value, "wc_wall": side, "bowl_in": round(bowl * 12, 1), "doors": len(boxes),
                    "target": [round(tx, 3), round(ty, 3)]})
        if g: rep["floor"] = {"id": g["floor_id"], "type": g["floor_type"], "pattern": g.get("pattern"), "gx": g.get("gx"), "gy": g.get("gy")}
        best = None
        if g and g.get("gx") and g.get("gy") and str(g["floor_id"]) in GRID:
            ox, oy = GRID[str(g["floor_id"])]; gx, gy = g["gx"], g["gy"]
            ix, iy = (tx - ox) / gx, (ty - oy) / gy
            for i in range(int(math.floor(ix)), int(math.ceil(ix)) + 1):
                for j in range(int(math.floor(iy)), int(math.ceil(iy)) + 1):
                    cx, cy = ox + i * gx, oy + j * gy
                    past = ok(cx, cy)
                    if past is None: continue
                    under_point = tile_grid(cx, cy, bb.Min.Z)
                    if not under_point or under_point["floor_id"] != g["floor_id"]: continue
                    dist = math.hypot(cx - tx, cy - ty)
                    if best is None or dist < best[0]: best = (dist, cx, cy, past)
            rep["mode"] = "snapped"
            if best is None:
                rep["skip"] = "ASK: no tile intersection passes the rules"; report.append(rep); continue
        else:
            past = ok(tx, ty)
            if past is None:
                rep["skip"] = "ASK: exact target fails the rules (door swing or wall)"; report.append(rep); continue
            best = (0.0, tx, ty, past)
            if g and g.get("gx") and g.get("gy"):
                rep["mode"] = "exact, NEEDS GRID MEASURE"
                needs.setdefault(str(g["floor_id"]), []).append(r.Number)
            else:
                rep["mode"] = "exact (no model tile pattern)"
        if RESNAP and rep["mode"] != "snapped":
            rep["skip"] = "ASK: resnap requires the measured tile grid"; report.append(rep); continue
        rep.update({"xy": [round(best[1], 3), round(best[2], 3)], "moved_ft": round(best[0], 2), "past_bowl_in": round(best[3] * 12, 1)})
        report.append(rep); plan.append((str(room_id), best[1], best[2], rep.get("drain_id")))

    for room_id in sorted(set(POINTS) - used_points):
        report.append({"room_id": room_id, "skip": "ASK: point does not identify a selected room in the target view"})
    if RESNAP:
        planned_ids = set(row[3] for row in plan)
        for drain_id in sorted(RESNAP_IDS - planned_ids):
            report.append({"drain_id": drain_id, "skip": "ASK: drain is not eligible for resnap in the target view"})

    made, zs = {}, {}
    if plan:
        title = "Snap floor drains to tile grid" if RESNAP else "Place floor drains"
        t = DB.Transaction(doc, title)
        t.Start()
        try:
            if RESNAP:
                for room_id, x, y, did in plan:
                    fi = doc.GetElement(EID(did)); p = fi.Location.Point
                    if abs(p.X - x) > 1e-4 or abs(p.Y - y) > 1e-4:
                        if not fi.Location.Move(DB.XYZ(x - p.X, y - p.Y, 0)):
                            raise RuntimeError("Could not move the approved drain: %s" % did)
                        made[room_id] = did
            else:
                if not sym.IsActive: sym.Activate(); doc.Regenerate()
                for room_id, x, y, _ in plan:
                    # With a Level, NewFamilyInstance reads Z as an offset from that level.
                    fi = doc.Create.NewFamilyInstance(DB.XYZ(x, y, 0), sym, level, DB.Structure.StructuralType.NonStructural)
                    prm = fi.get_Parameter(DB.BuiltInParameter.INSTANCE_ELEVATION_PARAM) or fi.get_Parameter(DB.BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM)
                    if prm and not prm.IsReadOnly: prm.Set(0.0)
                    made[room_id] = fi.Id.Value
                doc.Regenerate()
                zs = dict((n, round(doc.GetElement(EID(i)).Location.Point.Z - level.Elevation, 3)) for n, i in made.items())
                if any(z != 0 for z in zs.values()):
                    raise RuntimeError("A drain is not at the target level. Placement was rolled back.")
        except Exception:
            t.RollBack()
            raise
        t.Commit()
    result = {"level": level.Name, "NEEDS_GRID_MEASURE": needs,
              "ASK_USER": [x for x in report if str(x.get("skip", "")).startswith("ASK")], "rooms": report}
    if RESNAP:
        result["moved"] = made
    else:
        result.update({"placed": len(made), "created": made, "z_above_level_should_be_0": zs or None})

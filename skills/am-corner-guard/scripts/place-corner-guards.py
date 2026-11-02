# -*- coding: utf-8 -*-
# Place corner guards and CG keynote tags on one floor finish plan.
# Run with run_modify (dry_run first). Needs `inputs`:
#   view_id      int   target floor finish plan (a ViewPlan)
#   src_view_id  int   view that holds the template guard and its tag
#   tpl_tag_id   int   one existing single-guard keynote tag (the template)
#   family_name  str   optional, default "GM-W_PRT-CORNER_GUARD-100"
# Rules are in SKILL.md. Python 2.7 syntax (IronPython).
from pyrevit.api import DB
import math, System

LIST = System.Collections.Generic.List
FAM = inputs.get("family_name", "GM-W_PRT-CORNER_GUARD-100")
src = doc.GetElement(DB.ElementId(System.Int64(inputs["src_view_id"])))
view = doc.GetElement(DB.ElementId(System.Int64(inputs["view_id"])))
level = view.GenLevel
# Rooms whose OWN boundary is never used (small service rooms). Their outside
# corners still come from the neighbour room (corridor, lobby, classroom).
SKIP_ROOMS = ("SHAFT", "STORAGE", "LOCKER", "TOILET", "STAIR", "DRIVE THRU", "MECHANICAL",
              "IDF", "CUSTODIAL", "BACK-OF-HOUSE", "CAFE OFFICE", "PANTRY", "CLOSET", "JANITOR",
              "ELECTRICAL", "OFFICE", "TESTING ROOM", "GAME ROOM", "STUDENT COMMUTER LOUNGE",
              "STUDENT EVENT SPACE", "WORKSTATIONS", "LACTATION") +tuple(x.upper() for x in inputs.get("skip_rooms", []))
UNSURE_WALL_TYPES = ("I_E12_1F2",)   # user kept only about 1 in 4 of these
MERGE_FT = 9.0                       # two guards in one room, closer than this, share one tag
MARGIN = 0.4

tpl_tag = doc.GetElement(DB.ElementId(System.Int64(inputs["tpl_tag_id"])))
tpl_guard = doc.GetElement(list(tpl_tag.GetTaggedLocalElementIds())[0])
symbol = tpl_guard.Symbol
ws_id = tpl_guard.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM).AsInteger()
existing = [e for e in DB.FilteredElementCollector(doc, view.Id).OfCategory(DB.BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType()
            if isinstance(e, DB.FamilyInstance) and e.Symbol.FamilyName == FAM]

opts = DB.SpatialElementBoundaryOptions()
opts.SpatialElementBoundaryLocation = DB.SpatialElementBoundaryLocation.Finish


def kind(seg):
    eid = seg.ElementId
    if eid == DB.ElementId.InvalidElementId:
        return "none"
    el = doc.GetElement(eid)
    if el is None:
        return "none"
    if isinstance(el, DB.Wall):
        return "wall"
    c = el.Category.Name if el.Category else "?"
    return "sep" if "Separation" in c else ("link" if "Link" in c else c)


def wtype(seg):
    el = doc.GetElement(seg.ElementId) if seg.ElementId != DB.ElementId.InvalidElementId else None
    if isinstance(el, DB.Wall):
        return el.WallType.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
    return None


cands = []
skipped_unsure = {}
for r in DB.FilteredElementCollector(doc, view.Id).OfCategory(DB.BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
    if r.Area <= 0:
        continue
    name = (r.get_Parameter(DB.BuiltInParameter.ROOM_NAME).AsString() or "").upper()
    lobby = "ELEVATOR" in name and "LOBBY" in name
    if "ELEVATOR" in name and not lobby:      # elevator car rooms
        continue
    if not lobby and any(x in name for x in SKIP_ROOMS):
        continue
    for loop in (r.GetBoundarySegments(opts) or []):
        segs = list(loop)
        pts = [s.GetCurve().GetEndPoint(0) for s in segs]
        n = len(pts)
        area = sum(pts[i].X * pts[(i + 1) % n].Y - pts[(i + 1) % n].X * pts[i].Y for i in range(n)) / 2.0
        for i in range(n):
            p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
            v1 = (p1.X - p0.X, p1.Y - p0.Y)
            v2 = (p2.X - p1.X, p2.Y - p1.Y)
            l1 = math.hypot(*v1)
            l2 = math.hypot(*v2)
            if l1 < 0.05 or l2 < 0.05:
                continue
            cross = (v1[0] * v2[1] - v1[1] * v2[0]) / (l1 * l2)
            dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
            if abs(dot) > 0.2:                 # keep ~90 degree corners only
                continue
            if not ((cross < 0) if area > 0 else (cross > 0)):   # keep convex (wall sticks into room)
                continue
            k1 = kind(segs[i - 1])
            k2 = kind(segs[i])
            if lobby:
                # lobby corners are often wall+none (open jamb) or link+link
                if k1 == "none" and k2 == "none":
                    continue
                if "sep" in (k1, k2):
                    continue
            else:
                if k1 != "wall" or k2 != "wall":
                    continue
                t1 = wtype(segs[i - 1])
                t2 = wtype(segs[i])
                if t1 != t2:
                    continue
                if t1 in UNSURE_WALL_TYPES:
                    skipped_unsure[name] = skipped_unsure.get(name, 0) + 1
                    continue
            if any(math.hypot(p1.X - d["x"], p1.Y - d["y"]) < 0.05 for d in cands):
                continue
            if any(math.hypot(e.Location.Point.X - p1.X, e.Location.Point.Y - p1.Y) < 0.3 for e in existing):
                continue
            ub = (-v1[0] / l1, -v1[1] / l1)
            uo = (v2[0] / l2, v2[1] / l2)
            s = (ub[0] + uo[0], ub[1] + uo[1])
            sl = math.hypot(*s)
            s = (s[0] / sl, s[1] / sl)          # points into the solid corner
            cands.append({"x": p1.X, "y": p1.Y, "s": s, "room": r.Number, "rname": name})

FACE = {(-1, -1): (0, -1), (1, -1): (1, 0), (-1, 1): (-1, 0), (1, 1): (0, 1)}
SKIP_CATS = ("grid", "level", "reference", "scope", "matchline", "section", "elevation", "callout",
             "crop", "view", "camera", "title")


def bbox_rect(e):
    bb = e.get_BoundingBox(view)
    if bb is None:
        return None
    return [bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y]


obstacles = []
for e in DB.FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
    c = e.Category
    if c is None or c.CategoryType != DB.CategoryType.Annotation:
        continue
    if any(k in c.Name.lower() for k in SKIP_CATS):
        continue
    r = bbox_rect(e)
    if r is None or max(r[2] - r[0], r[3] - r[1]) > 40:
        continue
    obstacles.append(r)

t = DB.Transaction(doc, "Corner guards and tags")
t.Start()
# 1. Bring a template guard + tag pair into the target view. Copying the pair keeps the
#    keynote behaviour. IndependentTag.Create gives an EMPTY keynote text, so never use it.
ids = list(DB.ElementTransformUtils.CopyElements(src, LIST[DB.ElementId]([tpl_guard.Id, tpl_tag.Id]),
                                                 view, DB.Transform.Identity, DB.CopyPasteOptions()))
g0 = [doc.GetElement(i) for i in ids if isinstance(doc.GetElement(i), DB.FamilyInstance)][0]
t0 = [doc.GetElement(i) for i in ids if isinstance(doc.GetElement(i), DB.IndependentTag)][0]
# 2. Measure the tag text box.
pid = list(DB.ElementTransformUtils.CopyElement(doc, t0.Id, DB.XYZ(0, 0, 0)))[0]
probe = doc.GetElement(pid)
probe.HasLeader = False
doc.Regenerate()
bb = probe.get_BoundingBox(view)
W = bb.Max.X - bb.Min.X
H = bb.Max.Y - bb.Min.Y
OFF = ((bb.Min.X + bb.Max.X) / 2.0 - probe.TagHeadPosition.X, (bb.Min.Y + bb.Max.Y) / 2.0 - probe.TagHeadPosition.Y)
doc.Delete(probe.Id)


def box_at(h):
    cx = h[0] + OFF[0]
    cy = h[1] + OFF[1]
    return [cx - W / 2.0 - MARGIN, cy - H / 2.0 - MARGIN, cx + W / 2.0 + MARGIN, cy + H / 2.0 + MARGIN]


def overlaps(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def find_head(cx, cy, base_ang):
    for rad in (2.5, 3.0, 4.0, 5.5, 7.0, 9.0, 12.0):
        for da in (0, 45, -45, 90, -90, 135, -135, 180):
            a = base_ang + math.radians(da)
            h = (cx + rad * math.cos(a), cy + rad * math.sin(a))
            bx = box_at(h)
            if any(overlaps(bx, o) for o in obstacles):
                continue
            return h, True
    return (cx + 3.0 * math.cos(base_ang), cy + 3.0 * math.sin(base_ang)), False


# 3. Create the guards. Z must be 0 (NOT the level elevation, Revit adds the level again).
new = []
for c in cands:
    k = (int(round(c["s"][0] * 1.414)), int(round(c["s"][1] * 1.414)))
    f = FACE[k]
    pt = DB.XYZ(c["x"], c["y"], 0.0)
    inst = doc.Create.NewFamilyInstance(pt, symbol, level, DB.Structure.StructuralType.NonStructural)
    ang = math.atan2(f[1], f[0]) - math.pi / 2.0
    ang = math.atan2(math.sin(ang), math.cos(ang))
    if abs(ang) > 1e-6:
        DB.ElementTransformUtils.RotateElement(doc, inst.Id, DB.Line.CreateBound(pt, DB.XYZ(pt.X, pt.Y, pt.Z + 1)), ang)
    p = inst.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
    if p and not p.IsReadOnly:
        p.Set(ws_id)
    el = inst.get_Parameter(DB.BuiltInParameter.INSTANCE_ELEVATION_PARAM)
    if el and not el.IsReadOnly:
        el.Set(0.0)
    new.append((inst, c))
doc.Regenerate()
for inst, c in new:
    r = bbox_rect(inst)
    if r:
        obstacles.append(r)

# 4. Group guards: same room, within MERGE_FT, at most 2 per tag.
used = set()


def partner(i):
    c = new[i][1]
    best = None
    bd = 1e9
    for j in range(len(new)):
        if j == i or j in used:
            continue
        o = new[j][1]
        if o["room"] != c["room"]:
            continue
        d = math.hypot(o["x"] - c["x"], o["y"] - c["y"])
        if d <= MERGE_FT and d < bd:
            best = j
            bd = d
    return best


groups = []
for i in range(len(new)):
    if i in used:
        continue
    used.add(i)
    j = partner(i)
    if j is not None:
        used.add(j)
        groups.append([new[i], new[j]])
    else:
        groups.append([new[i]])

# 5. One tag per group: copy the template tag, re-point it, set head and leader ends.
ntags = 0
unresolved = 0
errs = []
for grp in groups:
    cx = sum(c["x"] for _, c in grp) / len(grp)
    cy = sum(c["y"] for _, c in grp) / len(grp)
    sx = sum(c["s"][0] for _, c in grp) / len(grp)
    sy = sum(c["s"][1] for _, c in grp) / len(grp)
    base = math.atan2(-sy, -sx)
    h, ok = find_head(cx, cy, base)
    if not ok:
        unresolved += 1
    try:
        tid = list(DB.ElementTransformUtils.CopyElement(doc, t0.Id, DB.XYZ(0, 0, 0)))[0]
        tg = doc.GetElement(tid)
        tg.AddReferences(LIST[DB.Reference]([DB.Reference(i) for i, _ in grp]))
        tg.RemoveReferences(LIST[DB.Reference]([DB.Reference(g0)]))
        tg.TagHeadPosition = DB.XYZ(h[0], h[1], level.Elevation)
        for i, _ in grp:
            # leader ends otherwise stay at the template guard (all leaders fan to one point)
            tg.SetLeaderEnd(DB.Reference(i), i.Location.Point)
        obstacles.append(box_at(h))
        ntags += 1
    except Exception as ex:
        errs.append(str(ex))
        if len(errs) > 2:
            break
doc.Delete(t0.Id)
doc.Delete(g0.Id)
t.Commit()

byroom = {}
for _, c in new:
    byroom[c["rname"]] = byroom.get(c["rname"], 0) + 1
result = {"guards": len(new), "tags": ntags, "merged_pairs": sum(1 for g in groups if len(g) == 2),
          "unresolved_overlap": unresolved, "errs": errs[:3], "by_room": byroom,
          "skipped_unsure_wall_type": skipped_unsure}

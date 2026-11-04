# -*- coding: utf-8 -*-
# Place corner guards and CG keynote tags on one floor finish plan.
# Corners come from WALLS (not room boundaries). See "Placement rules" in SKILL.md.
# Run with run_modify (dry_run first). Needs `inputs`:
#   view_id        int   target floor finish plan (a ViewPlan)
#   src_view_id    int   view that holds the template guard and its tag
#   tpl_tag_id     int   one existing single-guard keynote tag (the template)
#   family_name    str   optional, default "GM-W_PRT-CORNER_GUARD-100"
#   approve_rooms  list  optional, room-name parts the user approved (large open spaces)
#   skip_rooms     list  optional, extra room-name parts to skip
#   corridor_keys  list  optional, extra room-name parts that count as corridor
#   candidates_only bool optional, true = run with run_query, list the corners, place nothing
#   link_names     list  optional, linked models whose walls count (default ["Existing"])
#   place_link_corners bool optional, default false: corners from link walls are only listed
#                  (LINK_CORNERS_TO_REVIEW_by_room), not placed. true = place them like other corners.
# Python 2.7 syntax (IronPython).
from pyrevit.api import DB
import math, System

LIST = System.Collections.Generic.List
FAM = inputs.get("family_name", "GM-W_PRT-CORNER_GUARD-100")
view = doc.GetElement(DB.ElementId(System.Int64(inputs["view_id"])))
level = view.GenLevel
LZ = level.Elevation

# ---- Room classes. The room that the corner sticks INTO decides the class. -----------
CORRIDOR_KEYS = ("CORRIDOR", "LOBBY", "HALL", "VESTIBULE", "CIRCULATION") + tuple(x.upper() for x in inputs.get("corridor_keys", []))
# Large open spaces: never place without the user's answer (pass them in approve_rooms).
ASK_KEYS = ("WAITING", "WORKSTATION", "BULLPEN", "BREAKOUT", "OPEN", "LOUNGE", "EVENT")
# Small rooms, toilets, elevators, stairs: no guards inside. Their OUTSIDE corners come
# from the corridor next to them.
SKIP_KEYS = ("SHAFT", "ELECTRICAL", "OFFICE", "STORAGE", "CONFERENCE", "BOH", "BACK-OF-HOUSE", "MAIL", "COPY",
             "PANTRY", "LACTATION", "TOILET", "RESTROOM", "WC", "STAIR", "ELEVATOR", "MECHANICAL", "IDF",
             "CUSTODIAL", "JANITOR", "CLOSET", "LOCKER", "DRIVE THRU") + tuple(x.upper() for x in inputs.get("skip_rooms", []))
APPROVE = tuple(x.upper() for x in inputs.get("approve_rooms", []))
PLACE_LINK = bool(inputs.get("place_link_corners", False))   # default: link corners are only listed for review
MERGE_FT = 9.0     # two guards in one room, closer than this, share one tag
MARGIN = 0.4
EPS = 0.1          # ft, probe distance for the convex-corner test


def classify(name):
    if not name:
        # No room at the outward point (usually a model mistake). User rule 2026-11-03: never skip it
        # silently. It always goes to ASK_USER_by_room, and the user can approve it with
        # approve_rooms ["(NO ROOM)"] (the 7th floor has no CORRIDOR rooms, so it IS the corridor).
        return "place" if "(NO ROOM)" in APPROVE else "ask"
    if any(x in name for x in APPROVE):
        return "place"
    if any(x in name for x in CORRIDOR_KEYS):
        return "place"          # includes elevator lobbies (shown in by_room so the user can check)
    if any(x in name for x in ASK_KEYS):
        return "ask"
    if any(x in name for x in SKIP_KEYS):
        return "skip"
    return "ask"                # unknown room type: ask, do not guess


# ---- 1. Wall rectangles in plan (basic walls only, door openings cut out). -----------
def door_width(e):
    for obj in (e, e.Symbol):
        for bip in (DB.BuiltInParameter.DOOR_WIDTH, DB.BuiltInParameter.FAMILY_WIDTH_PARAM):
            p = obj.get_Parameter(bip)
            if p is not None and p.HasValue and p.AsDouble() > 0:
                return p.AsDouble()
    return 3.0


rects = []     # (x0, y0, ux, uy, lo, hi, hw, makes_corners, wall type name)
LINK_KEYS = tuple(x.upper() for x in inputs.get("link_names", ["Existing"]))   # linked models whose walls count


def to_host(tr, p):
    return tr.OfPoint(p) if tr is not None else p


def add_walls(wdoc, tr, prefix):
    # wdoc = the model that holds the walls, tr = link transform to host (None for the host model).
    for w in DB.FilteredElementCollector(wdoc).OfClass(DB.Wall):
        # Curtain and stacked walls only count as solid (a partition that meets glass has no
        # free corner there). They never make corners themselves.
        basic = w.WallType.Kind == DB.WallKind.Basic
        lc = w.Location
        if not isinstance(lc, DB.LocationCurve) or not isinstance(lc.Curve, DB.Line):
            continue
        bb = w.get_BoundingBox(None)
        if bb is None:
            continue
        zs = [to_host(tr, DB.XYZ(bb.Min.X, bb.Min.Y, z)).Z for z in (bb.Min.Z, bb.Max.Z)]
        if not (min(zs) <= LZ + 3.0 <= max(zs)):
            continue
        wtname = prefix + (w.WallType.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() or "")
        c = lc.Curve
        p0 = to_host(tr, c.GetEndPoint(0))
        p1 = to_host(tr, c.GetEndPoint(1))
        L = math.hypot(p1.X - p0.X, p1.Y - p0.Y)
        if L < 0.05:
            continue
        ux = (p1.X - p0.X) / L
        uy = (p1.Y - p0.Y) / L
        hw = w.Width / 2.0 if basic else max(w.Width / 2.0, 0.3)
        # A joined end grows by the half width of the joined wall. This closes the square that
        # is missing at an L corner, so the corner lands on the finished face.
        ext = []
        for end in (0, 1):
            e_hw = 0.0
            for o in lc.get_ElementsAtJoin(end):
                if isinstance(o, DB.Wall) and o.Id != w.Id:
                    e_hw = max(e_hw, o.Width / 2.0)
            ext.append(e_hw)
        cuts = []
        for iid in (w.FindInserts(True, False, False, False) if basic else []):
            e = wdoc.GetElement(iid)
            if (isinstance(e, DB.FamilyInstance) and e.Category is not None
                    and e.Category.Id.Value == int(DB.BuiltInCategory.OST_Doors)):
                dp = to_host(tr, e.Location.Point)
                s = (dp.X - p0.X) * ux + (dp.Y - p0.Y) * uy
                hd = door_width(e) / 2.0
                cuts.append((max(0.0, s - hd), min(L, s + hd)))
        cuts.sort()
        pieces = []
        cur = 0.0
        for a, b in cuts:
            if a > cur:
                pieces.append((cur, a))
            cur = max(cur, b)
        if cur < L:
            pieces.append((cur, L))
        for a, b in pieces:
            if b - a < 0.1:
                continue
            lo = a - (ext[0] if a <= 1e-6 else 0.0)
            hi = b + (ext[1] if b >= L - 1e-6 else 0.0)
            kind = "wrap" if "COLUMN WRAP" in wtname.upper() else "wall"
            rects.append((p0.X, p0.Y, ux, uy, lo, hi, hw, basic, wtname, kind))


def add_columns(wdoc, tr, prefix):
    # Rectangular columns as plan rectangles (kind "column"). Round columns have no corners.
    opt = DB.Options()
    for bic in (DB.BuiltInCategory.OST_Columns, DB.BuiltInCategory.OST_StructuralColumns):
        for e in DB.FilteredElementCollector(wdoc).OfCategory(bic).WhereElementIsNotElementType():
            if not isinstance(e, DB.FamilyInstance):
                continue
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            zs = [to_host(tr, DB.XYZ(bb.Min.X, bb.Min.Y, z)).Z for z in (bb.Min.Z, bb.Max.Z)]
            if not (min(zs) <= LZ + 3.0 <= max(zs)):
                continue
            bx = e.GetTransform().BasisX
            if tr is not None:
                bx = tr.OfVector(bx)
            bl = math.hypot(bx.X, bx.Y)
            if bl < 1e-6:
                continue
            ux = bx.X / bl
            uy = bx.Y / bl
            pts = []
            curved = False
            for g in e.get_Geometry(opt):
                geoms = g.GetInstanceGeometry() if isinstance(g, DB.GeometryInstance) else [g]
                for o in geoms:
                    if isinstance(o, DB.Solid) and o.Volume > 0:
                        for ed in o.Edges:
                            cv = ed.AsCurve()
                            if not isinstance(cv, DB.Line):
                                curved = True
                                break
                            for k in (0, 1):
                                p = to_host(tr, cv.GetEndPoint(k))
                                pts.append((p.X, p.Y))
                    if curved:
                        break
                if curved:
                    break
            if curved or len(pts) < 4:
                continue
            ox, oy = pts[0]
            ss = [(p[0] - ox) * ux + (p[1] - oy) * uy for p in pts]
            ts = [-(p[0] - ox) * uy + (p[1] - oy) * ux for p in pts]
            tc = (min(ts) + max(ts)) / 2.0
            hw = (max(ts) - min(ts)) / 2.0
            if hw < 0.15 or hw > 3.0 or (max(ss) - min(ss)) > 6.0:
                continue
            rects.append((ox - tc * uy, oy + tc * ux, ux, uy, min(ss), max(ss), hw, True, prefix + "COLUMN", "column"))


add_walls(doc, None, "")
add_columns(doc, None, "")
for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
    ld = li.GetLinkDocument()
    if ld is None:
        continue
    if any(k in li.Name.upper() for k in LINK_KEYS):
        add_walls(ld, li.GetTotalTransform(), "[link] ")
    # Columns come from every link (the structural link model holds them). Their corners are
    # not "link wall" corners, so the prefix is different.
    add_columns(ld, li.GetTotalTransform(), "[col-link] ")

CELL = 10.0
grid = {}


def rect_box(r):
    x0, y0, ux, uy, lo, hi, hw = r[:7]
    xs = []
    ys = []
    for s in (lo, hi):
        for t in (-hw, hw):
            xs.append(x0 + s * ux - t * uy)
            ys.append(y0 + s * uy + t * ux)
    return min(xs), min(ys), max(xs), max(ys)


for idx, r in enumerate(rects):
    bx0, by0, bx1, by1 = rect_box(r)
    for gx in range(int(math.floor(bx0 / CELL)), int(math.floor(bx1 / CELL)) + 1):
        for gy in range(int(math.floor(by0 / CELL)), int(math.floor(by1 / CELL)) + 1):
            grid.setdefault((gx, gy), []).append(idx)


def inside(x, y, room_walls_only=False):
    # room_walls_only: count only basic walls (not columns, column wraps or curtain walls)
    for idx in grid.get((int(math.floor(x / CELL)), int(math.floor(y / CELL))), ()):
        if room_walls_only and not (rects[idx][9] == "wall" and rects[idx][7]):
            continue
        x0, y0, ux, uy, lo, hi, hw = rects[idx][:7]
        dx = x - x0
        dy = y - y0
        s = dx * ux + dy * uy
        t = -dx * uy + dy * ux
        if lo - 1e-3 <= s <= hi + 1e-3 and abs(t) <= hw + 1e-3:
            return True
    return False


# ---- 2. Convex outside corners of the wall union. ------------------------------------
existing = [e for e in DB.FilteredElementCollector(doc, view.Id).OfCategory(DB.BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType()
            if isinstance(e, DB.FamilyInstance) and e.Symbol.FamilyName == FAM]

# Column rule: a column (or column wrap) makes corners only when it is attached to a room wall.
# Group touching column-like rectangles, then test if the group touches a basic wall.
col_ids = [i for i, r in enumerate(rects) if r[9] != "wall"]
boxes = dict((i, rect_box(rects[i])) for i in col_ids)
parent = dict((i, i) for i in col_ids)


def find(i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


for ai in range(len(col_ids)):
    for bi in range(ai + 1, len(col_ids)):
        a = boxes[col_ids[ai]]
        b = boxes[col_ids[bi]]
        if not (a[2] + 0.25 < b[0] or a[0] - 0.25 > b[2] or a[3] + 0.25 < b[1] or a[1] - 0.25 > b[3]):
            parent[find(col_ids[ai])] = find(col_ids[bi])
attached_roots = set()
for i in col_ids:
    x0, y0, ux, uy, lo, hi, hw = rects[i][:7]
    probes = []
    for sgn in (-1.0, 1.0):
        n = int((hi - lo) / 0.5) + 2
        for k in range(n + 1):
            s = (lo - 0.25) + (hi - lo + 0.5) * k / float(n)
            probes.append((s, sgn * (hw + 0.25)))
        n = int(hw * 2 / 0.5) + 2
        for k in range(n + 1):
            t = -(hw + 0.25) + (2 * hw + 0.5) * k / float(n)
            probes.append(((lo - 0.25) if sgn < 0 else (hi + 0.25), t))
    for s, t in probes:
        if inside(x0 + s * ux - t * uy, y0 + s * uy + t * ux, True):
            attached_roots.add(find(i))
            break
attached_idx = set(i for i in col_ids if find(i) in attached_roots)

corners = []
for ridx, r in enumerate(rects):
    if not r[7]:
        continue
    if r[9] != "wall" and ridx not in attached_idx:
        continue                      # free-standing column or wrap: no guards
    x0, y0, ux, uy, lo, hi, hw = r[:7]
    nx = -uy
    ny = ux
    for end_s, du in ((lo, 1.0), (hi, -1.0)):
        for side in (-1.0, 1.0):
            px = x0 + end_s * ux + side * hw * nx
            py = y0 + end_s * uy + side * hw * ny
            dux = du * ux
            duy = du * uy
            dnx = -side * nx
            dny = -side * ny
            solid = 0
            for a, b in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                if inside(px + EPS * (a * dux + b * dnx), py + EPS * (a * duy + b * dny)):
                    solid += 1
            if solid != 1:               # exactly one quadrant is solid = convex 90 degree corner
                continue
            sx = dux + dnx
            sy = duy + dny
            sl = math.hypot(sx, sy)
            sx /= sl
            sy /= sl                     # points into the solid corner
            if any(math.hypot(px - c["x"], py - c["y"]) < 0.15 for c in corners):
                continue
            corners.append({"x": px, "y": py, "s": (sx, sy), "wt": r[8], "kind": r[9], "link": r[8].startswith("[link]")})

# ---- 3. Classify each corner by the room it sticks into. -----------------------------
cands = []
counts = {"place": {}, "skip": {}, "ask": {}, "review": {}}
by_kind = {}
ask_samples = {}
dup_existing = 0
for c in corners:
    ox = c["x"] - c["s"][0] * 1.0
    oy = c["y"] - c["s"][1] * 1.0
    room = doc.GetRoomAtPoint(DB.XYZ(ox, oy, LZ + 3.0))
    name = (room.get_Parameter(DB.BuiltInParameter.ROOM_NAME).AsString() or "").upper() if room else ""
    cls = classify(name)
    if c["link"] and cls == "place" and not PLACE_LINK:
        cls = "review"       # link-wall corners are not automatic: the user judges them by program
    key = name or "(NO ROOM)"
    counts[cls][key] = counts[cls].get(key, 0) + 1
    if cls == "ask":
        ask_samples.setdefault(key, [])
        if len(ask_samples[key]) < 3:
            ask_samples[key].append([round(c["x"], 1), round(c["y"], 1)])
    if cls != "place":
        continue
    if any(math.hypot(e.Location.Point.X - c["x"], e.Location.Point.Y - c["y"]) < 0.3 for e in existing):
        dup_existing += 1
        continue
    c["room"] = room.Number if room else ""
    c["rname"] = key
    cands.append(c)
    by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    # (the "wt" key keeps the wall type name for analysis)

summary = {"wall_rects": len(rects), "convex_corners": len(corners), "to_place": len(cands),
           "already_has_guard": dup_existing, "to_place_by_kind": by_kind,
           "LINK_CORNERS_TO_REVIEW_by_room": counts["review"], "place_by_room": counts["place"],
           "skipped_by_room": counts["skip"], "ASK_USER_by_room": counts["ask"],
           "ask_sample_xy": ask_samples}

SKIP_CATS = ("grid", "level", "reference", "scope", "matchline", "section", "elevation", "callout",
             "crop", "view", "camera", "title")


def bbox_rect(e):
    bb = e.get_BoundingBox(view)
    if bb is None:
        return None
    return [bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y]


MAX_PER_TAG = 3    # 1 to 3 close guards share one tag
ALIGN_TOL = 0.05   # ft, heads count as aligned when X or Y differ less than this
ALIGN_RANGE = 25.0  # ft, look for tags to align with inside this distance


def box_hits_poly(box, pts):
    # Separating axis test. box = [x0, y0, x1, y1]; pts = polygon corners (2 points = a line).
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    if max(xs) < box[0] or min(xs) > box[2] or max(ys) < box[1] or min(ys) > box[3]:
        return False
    corners = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]
    n = len(pts)
    for i in range(n if n > 2 else 1):
        a = pts[i]
        b = pts[(i + 1) % n]
        nx = -(b[1] - a[1])
        ny = b[0] - a[0]
        if abs(nx) + abs(ny) < 1e-9:
            continue
        pa = [nx * p[0] + ny * p[1] for p in pts]
        pb = [nx * c[0] + ny * c[1] for c in corners]
        if max(pa) < min(pb) or min(pa) > max(pb):
            return False
    return True


class ObstacleGrid(object):
    # Boxes (pts None) and polygons/lines (pts given), hashed in 10 ft cells.
    def __init__(self):
        self.cells = {}

    def add(self, bbox, pts=None):
        item = (bbox, pts)
        for gx in range(int(math.floor(bbox[0] / 10.0)), int(math.floor(bbox[2] / 10.0)) + 1):
            for gy in range(int(math.floor(bbox[1] / 10.0)), int(math.floor(bbox[3] / 10.0)) + 1):
                self.cells.setdefault((gx, gy), []).append(item)

    def hits(self, box):
        for gx in range(int(math.floor(box[0] / 10.0)), int(math.floor(box[2] / 10.0)) + 1):
            for gy in range(int(math.floor(box[1] / 10.0)), int(math.floor(box[3] / 10.0)) + 1):
                for bb, pts in self.cells.get((gx, gy), ()):
                    if box[2] < bb[0] or box[0] > bb[2] or box[3] < bb[1] or box[1] > bb[3]:
                        continue
                    if pts is None or box_hits_poly(box, pts):
                        return True
        return False


def run_placement():
    tpl_tag = doc.GetElement(DB.ElementId(System.Int64(inputs["tpl_tag_id"])))
    tpl_guard = doc.GetElement(list(tpl_tag.GetTaggedLocalElementIds())[0])
    src = doc.GetElement(DB.ElementId(System.Int64(inputs["src_view_id"])))
    symbol = tpl_guard.Symbol
    ws_id = tpl_guard.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM).AsInteger()

    obstacles = ObstacleGrid()
    # Annotation: text notes (labels), room tags, finish/material tags, other tags, dimensions...
    for e in DB.FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
        c = e.Category
        if c is None or c.CategoryType != DB.CategoryType.Annotation:
            continue
        if any(k in c.Name.lower() for k in SKIP_CATS):
            continue
        r = bbox_rect(e)
        if r is None or max(r[2] - r[0], r[3] - r[1]) > 40:
            continue
        obstacles.add(r)
    # Walls (plan rectangles from step 1, including curtain walls).
    for r in rects:
        x0, y0, ux, uy, lo, hi, hw = r[:7]
        pts = [(x0 + s * ux - t * uy, y0 + s * uy + t * ux) for s, t in ((lo, -hw), (hi, -hw), (hi, hw), (lo, hw))]
        obstacles.add([min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)], pts)
    # Grid lines (the tag text must stay readable).
    for g in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Grid):
        gc = g.Curve
        if isinstance(gc, DB.Line):
            a = gc.GetEndPoint(0)
            b = gc.GetEndPoint(1)
            obstacles.add([min(a.X, b.X), min(a.Y, b.Y), max(a.X, b.X), max(a.Y, b.Y)], [(a.X, a.Y), (b.X, b.Y)])
    # Existing guards, and the heads of existing CG tags (to line the new tags up with them).
    for e in existing:
        r = bbox_rect(e)
        if r:
            obstacles.add(r)
    heads = []
    for tg in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.IndependentTag):
        try:
            tids = list(tg.GetTaggedLocalElementIds())
        except Exception:
            continue
        if any(isinstance(doc.GetElement(i), DB.FamilyInstance) and doc.GetElement(i).Symbol.FamilyName == FAM for i in tids):
            heads.append((tg.TagHeadPosition.X, tg.TagHeadPosition.Y))

    t = DB.Transaction(doc, "Corner guards and tags")
    t.Start()
    # Bring a template guard + tag pair into the target view. Copying the pair keeps the
    # keynote behaviour. IndependentTag.Create gives an EMPTY keynote text, so never use it.
    ids = list(DB.ElementTransformUtils.CopyElements(src, LIST[DB.ElementId]([tpl_guard.Id, tpl_tag.Id]),
                                                     view, DB.Transform.Identity, DB.CopyPasteOptions()))
    g0 = [doc.GetElement(i) for i in ids if isinstance(doc.GetElement(i), DB.FamilyInstance)][0]
    t0 = [doc.GetElement(i) for i in ids if isinstance(doc.GetElement(i), DB.IndependentTag)][0]
    # Measure the tag text box.
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

    def is_aligned(h):
        return any(abs(h[0] - a[0]) < ALIGN_TOL or abs(h[1] - a[1]) < ALIGN_TOL for a in heads
                   if math.hypot(h[0] - a[0], h[1] - a[1]) < ALIGN_RANGE)

    def pick_head(cx, cy, base_ang):
        # Candidate heads: a ring around the guard group, plus copies snapped to the X or Y of
        # the nearest existing CG tags. Sort by cost, return the first one that is clear.
        near = sorted((a for a in heads if math.hypot(a[0] - cx, a[1] - cy) < ALIGN_RANGE),
                      key=lambda a: math.hypot(a[0] - cx, a[1] - cy))[:3]
        cl = []
        for rad in (2.5, 3.0, 4.0, 5.5, 7.0, 9.0, 12.0):
            for da in (0, 45, -45, 90, -90, 135, -135, 180):
                a = base_ang + math.radians(da)
                h = (cx + rad * math.cos(a), cy + rad * math.sin(a))
                hs = [h]
                if rad <= 4.0:
                    for ax, ay in near:
                        hs.append((ax, h[1]))
                        hs.append((h[0], ay))
                for hh in hs:
                    d = math.hypot(hh[0] - cx, hh[1] - cy)
                    if d < 2.0 or d > 6.5 and rad <= 4.0 and hh is not h:
                        continue
                    al = is_aligned(hh)
                    cost = abs(d - 3.0) + abs(da) / 90.0 * 0.5 + (0.0 if al else 1.5) + (rad - 3.0) * 0.1
                    cl.append((cost, hh, al))
        cl.sort(key=lambda t: t[0])
        for cost, hh, al in cl:
            if not obstacles.hits(box_at(hh)):
                return hh, True, al
        return (cx + 3.0 * math.cos(base_ang), cy + 3.0 * math.sin(base_ang)), False, False

    # Create the guards. Z must be 0 (NOT the level elevation, Revit adds the level again).
    new = []
    for c in cands:
        pt = DB.XYZ(c["x"], c["y"], 0.0)
        inst = doc.Create.NewFamilyInstance(pt, symbol, level, DB.Structure.StructuralType.NonStructural)
        # Rotation: the family faces (solid-corner direction + 45 deg) minus 90 deg.
        ang = math.atan2(c["s"][1], c["s"][0]) - math.pi / 4.0
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
            obstacles.add(r)

    # Group guards: same room, all within MERGE_FT of each other, at most MAX_PER_TAG per tag.
    used = set()

    def mates(i):
        c = new[i][1]
        near = []
        for j in range(len(new)):
            if j == i or j in used:
                continue
            o = new[j][1]
            if o["room"] != c["room"]:
                continue
            d = math.hypot(o["x"] - c["x"], o["y"] - c["y"])
            if d <= MERGE_FT:
                near.append((d, j))
        near.sort()
        chosen = []
        for d, j in near:
            if len(chosen) >= MAX_PER_TAG - 1:
                break
            o = new[j][1]
            if all(math.hypot(o["x"] - new[k][1]["x"], o["y"] - new[k][1]["y"]) <= MERGE_FT for k in chosen):
                chosen.append(j)
        return chosen

    groups = []
    for i in sorted(range(len(new)), key=lambda k: (new[k][1]["y"], new[k][1]["x"])):
        if i in used:
            continue
        used.add(i)
        m = mates(i)
        for j in m:
            used.add(j)
        groups.append([new[i]] + [new[j] for j in m])

    # One tag per group: copy the template tag, re-point it, set head and leader ends.
    ntags = 0
    unresolved = 0
    aligned_n = 0
    not_free = 0
    errs = []
    for grp in groups:
        cx = sum(c["x"] for _, c in grp) / len(grp)
        cy = sum(c["y"] for _, c in grp) / len(grp)
        sx = sum(c["s"][0] for _, c in grp) / len(grp)
        sy = sum(c["s"][1] for _, c in grp) / len(grp)
        base = math.atan2(-sy, -sx)
        h, ok, al = pick_head(cx, cy, base)
        if not ok:
            unresolved += 1
        try:
            tid = list(DB.ElementTransformUtils.CopyElement(doc, t0.Id, DB.XYZ(0, 0, 0)))[0]
            tg = doc.GetElement(tid)
            tg.AddReferences(LIST[DB.Reference]([DB.Reference(i) for i, _ in grp]))
            tg.RemoveReferences(LIST[DB.Reference]([DB.Reference(g0)]))
            # Leader on, end condition Free (user rule). A Free end must be set by hand for each
            # guard, or all leaders stay at the template guard's spot.
            tg.HasLeader = True
            if tg.CanLeaderEndConditionBeAssigned(DB.LeaderEndCondition.Free):
                tg.LeaderEndCondition = DB.LeaderEndCondition.Free
            else:
                not_free += 1
            tg.TagHeadPosition = DB.XYZ(h[0], h[1], LZ)
            for i, _ in grp:
                tg.SetLeaderEnd(DB.Reference(i), i.Location.Point)
            obstacles.add(box_at(h))
            heads.append(h)
            ntags += 1
            if al:
                aligned_n += 1
        except Exception as ex:
            errs.append(str(ex))
            if len(errs) > 2:
                break
    doc.Delete(t0.Id)
    doc.Delete(g0.Id)
    t.Commit()
    sizes = {}
    for g in groups:
        sizes[len(g)] = sizes.get(len(g), 0) + 1
    return {"guards": len(new), "tags": ntags, "guards_per_tag": sizes, "aligned_tags": aligned_n,
            "leader_not_free": not_free, "unresolved_overlap": unresolved, "errs": errs[:3]}


if inputs.get("candidates_only"):
    summary["corner_xy"] = [[round(c["x"], 2), round(c["y"], 2)] for c in cands][:200]
    result = summary
else:
    placed = run_placement()
    placed.update(summary)
    result = placed

# -*- coding: utf-8 -*-
"""Collect dry-run content inside Revit for dry_run_checks.py (issue #256).

Use it at the end of an apply script, inside the transaction, before the
script commits. Run the apply script with run_modify and set the run
"workspace" to this scripts folder, so that the import works:

    import dry_run_content
    content = dry_run_content.collect(doc, view_id, new_ids,
                                      value_reads=[(floor_id, "Area")])
    result = {"rows": rows, "content": content}

collect() calls doc.Regenerate() first, so computed values (area, length,
volume, tag text) are current. It only reads. It changes nothing.

view_id     : the TARGET view (an id), never doc.ActiveView. The active
              view can be a sheet after a view change.
new_ids     : ids of the elements the script created or moved. Tags and
              text notes in this list are also checked as tags.
tag_ids     : more tag or text note ids to check (optional).
value_reads : [(element_id, parameter_name), ...] computed values to read.

The content shape is in scripts/lib/run_checks.py.
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import sys

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"  # IronPython result encoder is ASCII-only (see read_sheets.py)


def txt(s):
    if s is None:
        return None
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


def id_int(element_id):
    try:
        return int(element_id.Value)        # Revit 2024+
    except AttributeError:
        return int(element_id.IntegerValue)  # removed in Revit 2026


try:
    import System

    def eid(n):
        return DB.ElementId(System.Int64(int(n)))
except ImportError:
    def eid(n):
        return DB.ElementId(int(n))


def xyz(p):
    if p is None:
        return None
    return [float(p.X), float(p.Y), float(p.Z)]


def world_box(box):
    """{"min", "max"} of a BoundingBoxXYZ in world coordinates, or None."""
    if box is None:
        return None
    t = box.Transform
    pts = []
    for x in (box.Min.X, box.Max.X):
        for y in (box.Min.Y, box.Max.Y):
            for z in (box.Min.Z, box.Max.Z):
                p = DB.XYZ(x, y, z)
                pts.append(t.OfPoint(p) if t is not None else p)
    return {"min": [min(p.X for p in pts), min(p.Y for p in pts), min(p.Z for p in pts)],
            "max": [max(p.X for p in pts), max(p.Y for p in pts), max(p.Z for p in pts)]}


def category_name(element):
    try:
        cat = element.Category
        return txt(cat.Name) if cat is not None else None
    except Exception:
        return None


def element_name(element):
    try:
        return txt(element.Name)
    except Exception:
        return ""


def _plane_z(doc, view, view_range, plane):
    """Absolute elevation of one view range plane, or None for no limit."""
    try:
        level_id = view_range.GetLevelId(plane)
    except Exception:
        return None
    if level_id is None or level_id == DB.ElementId.InvalidElementId:
        return None
    try:
        if level_id == DB.PlanViewRange.Current:
            level_id = view.GenLevel.Id
        elif level_id in (DB.PlanViewRange.Unlimited, DB.PlanViewRange.LevelBelow,
                          DB.PlanViewRange.LevelAbove):
            return None
    except AttributeError:
        pass
    level = doc.GetElement(level_id)
    if level is None or not isinstance(level, DB.Level):
        return None
    return float(level.ProjectElevation) + float(view_range.GetOffset(plane))


def describe_view(doc, view):
    """Name, view range (plans) and active crop of the target view."""
    out = {"id": id_int(view.Id), "name": element_name(view),
           "view_range": {"bottom": None, "top": None}, "crop": None}
    if isinstance(view, DB.ViewPlan):
        vr = view.GetViewRange()
        out["view_range"] = {
            "bottom": _plane_z(doc, view, vr, DB.PlanViewPlane.ViewDepthPlane),
            "top": _plane_z(doc, view, vr, DB.PlanViewPlane.TopClipPlane)}
    try:
        active = view.CropBoxActive
    except Exception:
        active = False
    if active and view.CropBox is not None:
        box = view.CropBox
        t = box.Transform
        out["crop"] = {"origin": xyz(t.Origin), "basis_x": xyz(t.BasisX),
                       "basis_y": xyz(t.BasisY), "min": xyz(box.Min), "max": xyz(box.Max)}
    return out


def describe_element(doc, view, element):
    hidden = False
    try:
        hidden = bool(element.IsHidden(view))
    except Exception:
        hidden = False
    return {"id": id_int(element.Id), "category": category_name(element),
            "name": element_name(element),
            "bbox": world_box(element.get_BoundingBox(None)), "hidden": hidden}


def is_tag(element):
    for name in ("IndependentTag", "TextNote", "SpatialElementTag"):
        cls = getattr(DB, name, None)
        if cls is not None and isinstance(element, cls):
            return True
    return False


def describe_tag(doc, tag):
    """Text, leader ends and host boxes of one tag or text note."""
    row = {"id": id_int(tag.Id), "category": category_name(tag), "text": None,
           "has_leader": False, "leader_ends": [], "host_ids": [], "host_boxes": []}
    if isinstance(tag, DB.TextNote):
        row["text"] = txt(tag.Text)
        return row
    try:
        row["text"] = txt(tag.TagText)
    except Exception:
        row["text"] = None
    try:
        row["has_leader"] = bool(tag.HasLeader)
    except Exception:
        row["has_leader"] = False
    hosts = []
    try:
        hosts = list(tag.GetTaggedLocalElementIds())
    except Exception:
        try:
            hosts = [tag.TaggedLocalRoomId]
        except Exception:
            hosts = []
    for host_id in hosts:
        host = doc.GetElement(host_id)
        row["host_ids"].append(id_int(host_id))
        row["host_boxes"].append(world_box(host.get_BoundingBox(None)) if host is not None else None)
    if not row["has_leader"]:
        return row
    try:
        free = tag.LeaderEndCondition == DB.LeaderEndCondition.Free
    except Exception:
        free = True
    if not free:
        return row  # an attached leader ends on its host
    try:
        for ref in tag.GetTaggedReferences():
            row["leader_ends"].append(xyz(tag.GetLeaderEnd(ref)))
    except Exception:
        try:
            row["leader_ends"].append(xyz(tag.LeaderEnd))
        except Exception:
            pass
    return row


def read_value(element, name):
    param = element.LookupParameter(name) if element is not None else None
    if param is None or not param.HasValue:
        return None
    storage = param.StorageType
    if storage == DB.StorageType.Double:
        return float(param.AsDouble())
    if storage == DB.StorageType.Integer:
        return int(param.AsInteger())
    if storage == DB.StorageType.ElementId:
        return id_int(param.AsElementId())
    return txt(param.AsString())


def collect(doc, view_id, new_ids, tag_ids=None, value_reads=None):
    """The dry-run content dict for dry_run_checks.py content."""
    doc.Regenerate()
    view = doc.GetElement(eid(view_id))
    if view is None or not isinstance(view, DB.View):
        raise ValueError("Target view %s does not exist." % view_id)
    content = {"regenerated": True, "view": describe_view(doc, view),
               "elements": [], "tags": [], "values": [], "escaped": ESCAPE}
    seen_tags = set()
    for n in list(new_ids or []) + list(tag_ids or []):
        element = doc.GetElement(eid(n))
        if element is None:
            content["elements"].append({"id": int(n), "category": None, "name": "",
                                        "bbox": None, "hidden": False})
            continue
        if is_tag(element):
            if int(n) not in seen_tags:
                seen_tags.add(int(n))
                content["tags"].append(describe_tag(doc, element))
            continue
        content["elements"].append(describe_element(doc, view, element))
    for n, name in value_reads or []:
        element = doc.GetElement(eid(n))
        content["values"].append({"id": int(n), "name": txt(name), "value": read_value(element, name)})
    return content

# -*- coding: utf-8 -*-
"""READ step for the detail-annotation recipe (issue #298). Read-only (run_query).

inputs: {"view_id": <target detail view id>,
         "reference_view_ids": [<finished detail view ids>],   (optional)
         "sheet_ids": [<sheet ids>]}                           (optional)
The views placed on the listed sheets are read as references too. At
most 40 views in one read.

For each view it returns the view frame and the 2D annotation that the
recipe copies the style from. Every point is in view coordinates: u to
the right and v up, in feet, from View.Origin along View.RightDirection
and View.UpDirection.

result = {"kind": "detail-annotation-read", "document": <title>,
          "target_view_id": id,
          "views": [{"id", "name", "scale", "view_type",
                     "origin": [x, y, z], "right": [x, y, z], "up": [x, y, z],
                     "crop_uv": {"min": [u, v], "max": [u, v]} or null,
                     "filled_regions": [{"id", "type_id", "type_name", "loops": [[[u, v], ...]]}],
                     "detail_lines": [{"id", "style_id", "style_name", "start": [u, v], "end": [u, v]}],
                     "text_notes": [{"id", "type_id", "type_name", "text", "coord": [u, v],
                                     "align", "leader_left",
                                     "leaders": [{"end": [u, v], "elbow": [u, v], "anchor": [u, v]}]}]}],
          "filled_region_types": [{"id", "name"}],
          "line_styles": [{"id", "name"}],
          "text_note_types": [{"id", "name"}],
          "missing": [ids not found or not views], "escaped": bool}
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import sys

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"  # IronPython result encoder is ASCII-only (see read_sheets.py)
MAX_VIEWS = 40


def txt(s):
    if s is None or not ESCAPE:
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
    return [p.X, p.Y, p.Z]


def element_name(element):
    if element is None:
        return None
    try:
        return element.Name
    except Exception:
        param = element.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        return param.AsString() if param is not None else None


class Frame(object):
    def __init__(self, view):
        self.o = view.Origin
        self.r = view.RightDirection
        self.u = view.UpDirection

    def uv(self, p):
        dx, dy, dz = p.X - self.o.X, p.Y - self.o.Y, p.Z - self.o.Z
        return [round(dx * self.r.X + dy * self.r.Y + dz * self.r.Z, 6),
                round(dx * self.u.X + dy * self.u.Y + dz * self.u.Z, 6)]


def crop_uv(view, frame):
    try:
        if not view.CropBoxActive:
            return None
        box = view.CropBox
    except Exception:
        return None
    if box is None:
        return None
    t = box.Transform
    us, vs = [], []
    for x in (box.Min.X, box.Max.X):
        for y in (box.Min.Y, box.Max.Y):
            p = t.OfPoint(DB.XYZ(x, y, box.Min.Z))
            u, v = frame.uv(p)
            us.append(u)
            vs.append(v)
    return {"min": [min(us), min(vs)], "max": [max(us), max(vs)]}


def curve_loop_points(loop, frame):
    pts = []
    for curve in loop:
        pts.append(frame.uv(curve.GetEndPoint(0)))
    return pts


def enum_name(value):
    try:
        return str(value).split(".")[-1]
    except Exception:
        return None


def read_view(view):
    frame = Frame(view)
    regions, lines, notes = [], [], []
    collector = DB.FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()  # noqa: F821
    for el in collector:
        if isinstance(el, DB.FilledRegion):
            type_id = el.GetTypeId()
            regions.append({"id": id_int(el.Id), "type_id": id_int(type_id),
                            "type_name": txt(element_name(doc.GetElement(type_id))),  # noqa: F821
                            "loops": [curve_loop_points(loop, frame) for loop in el.GetBoundaries()]})
        elif isinstance(el, DB.DetailCurve):
            curve = el.GeometryCurve
            style = el.LineStyle
            if curve is None or not curve.IsBound:
                continue
            lines.append({"id": id_int(el.Id),
                          "style_id": id_int(style.Id) if style is not None else None,
                          "style_name": txt(style.Name) if style is not None else None,
                          "start": frame.uv(curve.GetEndPoint(0)), "end": frame.uv(curve.GetEndPoint(1))})
        elif isinstance(el, DB.TextNote):
            type_id = el.GetTypeId()
            leaders = []
            for leader in el.GetLeaders():
                row = {}
                for key, attr in (("end", "End"), ("elbow", "Elbow"), ("anchor", "Anchor")):
                    try:
                        row[key] = frame.uv(getattr(leader, attr))
                    except Exception:
                        row[key] = None
                leaders.append(row)
            notes.append({"id": id_int(el.Id), "type_id": id_int(type_id),
                          "type_name": txt(element_name(doc.GetElement(type_id))),  # noqa: F821
                          "text": txt(el.Text), "coord": frame.uv(el.Coord),
                          "align": enum_name(el.HorizontalAlignment),
                          "leader_left": enum_name(el.LeaderLeftAttachment),
                          "leaders": leaders})
    return {"id": id_int(view.Id), "name": txt(view.Name), "scale": view.Scale,
            "view_type": enum_name(view.ViewType),
            "origin": xyz(frame.o), "right": xyz(frame.r), "up": xyz(frame.u),
            "crop_uv": crop_uv(view, frame),
            "filled_regions": regions, "detail_lines": lines, "text_notes": notes}


def named_rows(elements):
    rows = []
    for el in elements:
        rows.append({"id": id_int(el.Id), "name": txt(element_name(el))})
    return sorted(rows, key=lambda r: (r["name"] or "", r["id"]))


def line_styles():
    rows = []
    lines_cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)  # noqa: F821
    for sub in lines_cat.SubCategories:
        style = sub.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
        if style is not None:
            rows.append({"id": id_int(style.Id), "name": txt(sub.Name)})
    return sorted(rows, key=lambda r: (r["name"] or "", r["id"]))


def main():
    if doc is None or doc.IsFamilyDocument:  # noqa: F821
        return {"error": "no_project_document", "message": "Open a project model."}
    target = inputs.get("view_id")  # noqa: F821
    if target is None:
        return {"error": "bad_inputs", "message": "inputs needs view_id."}
    ids = [int(target)] + [int(i) for i in inputs.get("reference_view_ids") or []]  # noqa: F821
    missing = []
    for sid in inputs.get("sheet_ids") or []:  # noqa: F821
        sheet = doc.GetElement(eid(sid))  # noqa: F821
        if not isinstance(sheet, DB.ViewSheet):
            missing.append(int(sid))
            continue
        for vid in sheet.GetAllPlacedViews():
            ids.append(id_int(vid))
    seen, ordered = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            ordered.append(i)
    if len(ordered) > MAX_VIEWS:
        return {"error": "bad_inputs",
                "message": "%d views. Read at most %d views at a time." % (len(ordered), MAX_VIEWS)}
    views = []
    for i in ordered:
        view = doc.GetElement(eid(i))  # noqa: F821
        if not isinstance(view, DB.View) or isinstance(view, DB.ViewSheet) or view.IsTemplate:
            missing.append(i)
            continue
        views.append(read_view(view))
    region_types = DB.FilteredElementCollector(doc).OfClass(DB.FilledRegionType)  # noqa: F821
    note_types = DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType)  # noqa: F821
    return {"kind": "detail-annotation-read", "document": txt(doc.Title),  # noqa: F821
            "target_view_id": int(target), "views": views,
            "filled_region_types": named_rows(region_types),
            "line_styles": line_styles(),
            "text_note_types": named_rows(note_types),
            "missing": missing, "escaped": ESCAPE}


result = main()

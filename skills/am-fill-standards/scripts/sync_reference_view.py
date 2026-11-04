# -*- coding: utf-8 -*-
"""am-fill-standards: apply a reference view sync plan in Revit.

Submit with the pyrevit MCP tool run_modify ONLY through am-safe-change:
the agent shows the plan first, the user approves it, am-safe-change
dry runs it, and Revit asks Keep/Discard. Never submit this script
directly. IronPython 2.7 compatible: no f-strings, no type hints.

Inputs (dict):
    {"view_id": 123,
     "template_swatch_id": 456, "template_label_id": 789,
     "label_rewrites": [{"label_id": 1, "text": "HATCH\nDRFT-X"}],
     "new_swatches": [{"type_id": 2, "cx": 10.5, "cy": 3.0}]}

label_rewrites sets a label to its swatch type's two-line label text.
new_swatches copies the template swatch: the boundary loops of the
template move to the given center (cx, cy, in feet, view coordinates),
the new region takes the missing type, and a new label of the template
text type goes under it, placed where the template label sits relative
to its swatch. Stale swatches are never deleted here: the plan flags
them, and the user decides what to remove.

Result: {"status": "ok" or "stopped", "labels_rewritten": [ids],
"swatches_created": [{"type_id", "region_id", "label_id"}],
"failed": [{"kind", "id", "message"}]}. One failure stops nothing else:
every other item still applies, and "failed" names each one. A
transaction wraps the whole apply, so a hard error rolls everything
back instead of leaving half a sync.
"""
from System.Collections.Generic import List  # noqa: F401 (IronPython .NET)

from pyrevit.api import DB

try:
    INPUTS = inputs  # noqa: F821  (injected by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}


def eid(element_id):
    """ElementId -> int. Revit 2024+ has .Value; 2023 and older only .IntegerValue."""
    if hasattr(element_id, "Value"):
        return int(element_id.Value)
    return int(element_id.IntegerValue)


def center_of(element, view):
    """Bounding box center (cx, cy) in feet, or (None, None)."""
    try:
        box = element.get_BoundingBox(view)
    except Exception:
        return None, None
    if box is None:
        return None, None
    try:
        return ((box.Min.X + box.Max.X) / 2.0,
                (box.Min.Y + box.Max.Y) / 2.0)
    except Exception:
        return None, None


def translated_loops(template, dx, dy):
    """Template swatch boundary loops moved by (dx, dy) feet.

    Returns a .NET List of CurveLoop, or None when the template has no
    usable boundaries. Curves move with a translation transform, so the
    copy keeps the template size, shape and line style.
    """
    try:
        boundaries = template.GetBoundaries()
    except Exception:
        return None
    shift = DB.Transform.CreateTranslation(DB.XYZ(dx, dy, 0.0))
    loops = List[DB.CurveLoop]()
    for loop_curves in boundaries:
        curves = List[DB.Curve]()
        for curve in loop_curves:
            try:
                curves.Add(curve.CreateTransformed(shift))
            except Exception:
                return None
        try:
            loops.Add(DB.CurveLoop.Create(curves))
        except Exception:
            return None
    if loops.Count == 0:
        return None
    return loops


result = {"status": "ok", "labels_rewritten": [],
          "swatches_created": [], "failed": []}
view = doc.GetElement(eid(INPUTS.get("view_id")))  # noqa: F821
if view is None or not isinstance(view, DB.View):
    result = {"status": "stopped",
              "message": "The reference view is not in the model any more."}
else:
    template = doc.GetElement(eid(INPUTS.get("template_swatch_id")))  # noqa: F821
    template_label = doc.GetElement(eid(INPUTS.get("template_label_id")))  # noqa: F821
    if template is None or not isinstance(template, DB.FilledRegion):
        result = {"status": "stopped",
                  "message": "The template swatch is not in the model any more."}
    elif template_label is None or not isinstance(template_label, DB.TextNote):
        result = {"status": "stopped",
                  "message": "The template label is not in the model any more."}
    else:
        t_cx, t_cy = center_of(template, view)
        l_cx, l_cy = center_of(template_label, view)
        if t_cx is None or l_cx is None:
            result = {"status": "stopped",
                      "message": "The template swatch or label has no "
                                 "bounding box, so copies cannot be placed."}
        else:
            label_dx = l_cx - t_cx
            label_dy = l_cy - t_cy
            try:
                text_type_id = eid(template_label.GetTypeId())
            except Exception:
                text_type_id = doc.GetDefaultElementTypeId(  # noqa: F821
                    DB.ElementTypeGroup.TextNoteType)
            t = DB.Transaction(doc, "Fill standards: sync reference view")
            t.Start()
            try:
                for item in INPUTS.get("label_rewrites") or []:
                    try:
                        note = doc.GetElement(eid(item["label_id"]))  # noqa: F821
                        if note is None or not isinstance(note, DB.TextNote):
                            raise ValueError("not a text note any more")
                        note.Text = item["text"]
                        result["labels_rewritten"].append(item["label_id"])
                    except Exception as e:
                        result["failed"].append(
                            {"kind": "label", "id": item.get("label_id"),
                             "message": str(e)[:160]})
                for item in INPUTS.get("new_swatches") or []:
                    try:
                        loops = translated_loops(
                            template,
                            float(item["cx"]) - t_cx,
                            float(item["cy"]) - t_cy)
                        if loops is None:
                            raise ValueError("template has no boundaries")
                        region = DB.FilledRegion.Create(
                            doc, view.Id, eid(item["type_id"]), loops)
                        if region is None:
                            raise ValueError("region create returned None")
                        origin = DB.XYZ(float(item["cx"]) + label_dx,
                                        float(item["cy"]) + label_dy, 0.0)
                        opts = DB.TextNoteOptions(text_type_id)
                        note = DB.TextNote.Create(
                            doc, view.Id, origin, 0.5,
                            item.get("label_text", ""), opts)
                        if note is None:
                            raise ValueError("label create returned None")
                        result["swatches_created"].append(
                            {"type_id": item["type_id"],
                             "region_id": eid(region.Id),
                             "label_id": eid(note.Id)})
                    except Exception as e:
                        result["failed"].append(
                            {"kind": "swatch", "id": item.get("type_id"),
                             "message": str(e)[:160]})
                t.Commit()
            except Exception as e:
                t.RollBack()
                result = {"status": "stopped",
                          "message": "Rolled back: %s" % str(e)[:160]}

# -*- coding: utf-8 -*-
# Read-only check (run_query). inputs: {"view_id": int}
# Reports tag text, untagged guards and leader ends that are far from their guard.
from pyrevit.api import DB
import math, System

FAM = inputs.get("family_name", "GM-W_PRT-CORNER_GUARD-100")
view = doc.GetElement(DB.ElementId(System.Int64(inputs["view_id"])))
guards = [e for e in DB.FilteredElementCollector(doc, view.Id).OfCategory(DB.BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType()
          if isinstance(e, DB.FamilyInstance) and e.Symbol.FamilyName == FAM]
tagged = set()
empty_text = 0
far_leader = 0
sizes = {}
for tg in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.IndependentTag):
    ids = [i.Value for i in tg.GetTaggedLocalElementIds()]
    if not ids:
        continue
    # only tags that point at a guard; other tags in the view are not ours
    if not any(isinstance(doc.GetElement(DB.ElementId(System.Int64(i))), DB.FamilyInstance)
               and doc.GetElement(DB.ElementId(System.Int64(i))).Symbol.FamilyName == FAM for i in ids):
        continue
    if tg.TagText == "":
        empty_text += 1
    for ref in tg.GetTaggedReferences():
        g = doc.GetElement(ref.ElementId)
        if not isinstance(g, DB.FamilyInstance) or g.Symbol.FamilyName != FAM:
            continue
        tagged.add(g.Id.Value)
        try:
            e = tg.GetLeaderEnd(ref)
            if math.hypot(e.X - g.Location.Point.X, e.Y - g.Location.Point.Y) > 3.0:
                far_leader += 1
        except Exception:
            pass
    sizes[len(ids)] = sizes.get(len(ids), 0) + 1
result = {"guards": len(guards), "untagged_guards": len([g for g in guards if g.Id.Value not in tagged]),
          "tags_with_empty_text": empty_text, "leader_ends_far_from_guard": far_leader, "guards_per_tag": sizes}

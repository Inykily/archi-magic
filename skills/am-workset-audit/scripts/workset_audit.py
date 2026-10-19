# -*- coding: utf-8 -*-
"""am-workset-audit, step 1: READ-ONLY workset audit (run with run_query).

Runs on the pyRevit Agent Runtime, IronPython 2.7 (no f-strings) or CPython 3.
Adapted from Utopia5327/claude-plugin-for-revit-bim skills/workset-manager (MIT),
rewritten for pyRevit (no Dynamo DocumentManager / IN / OUT).

inputs (all optional):
  rules                 list of rule ids to apply. Default: ["links", "levels_grids", "workset1"]
                          "links"         Revit link instances not on the links workset
                          "levels_grids"  levels and grids not on the levels-and-grids workset
                          "workset1"      model elements left on the default workset (report only)
                          "categories"    elements whose category is in category_map but sit
                                          on another workset
  links_workset         exact name of the target workset for links
  levels_grids_workset  exact name of the target workset for levels and grids
  default_workset       name of the default workset. Default: "Workset1"
  category_map          {"OST_Walls": "Exterior", ...}: BuiltInCategory name -> exact workset name
  max_items             cap on listed findings. Default: 500

result: worksets with element counts, findings, and "moves" (only movable elements) in the
exact shape that workset_fix.py takes as its "moves" input.
"""
from pyrevit.api import DB

try:
    inputs
except NameError:
    inputs = {}
inputs = inputs or {}


def eid_int(element_id):
    """ElementId -> int. Revit 2024+ has .Value; .IntegerValue is gone in 2026."""
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def find_workset(worksets, wanted, hints):
    """Exact (case-insensitive) name match first; else guess by hint substrings.
    Returns (workset or None, list of candidate names)."""
    if wanted:
        for ws in worksets:
            if ws.Name.lower() == wanted.lower():
                return ws, [ws.Name]
        return None, []
    cands = [ws for ws in worksets if any(h in ws.Name.lower() for h in hints)]
    if len(cands) == 1:
        return cands[0], [cands[0].Name]
    return None, [c.Name for c in cands]


def movable(el):
    """(True, "") when the element workset can be changed, else (False, reason)."""
    p = el.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
    if p is None or p.IsReadOnly:
        return False, "workset is read-only (follows its host or is fixed)"
    if el.GroupId != DB.ElementId.InvalidElementId:
        return False, "element is inside a group"
    status = DB.WorksharingUtils.GetCheckoutStatus(doc, el.Id)
    if status == DB.CheckoutStatus.OwnedByOtherUser:
        return False, "element is borrowed by another user"
    return True, ""


def main():
    if doc is None:
        return {"status": "no_active_document",
                "message": "Open a model in Revit, then run the audit again."}
    if doc.IsFamilyDocument:
        return {"status": "family_document",
                "message": "The active document is a family. Worksets apply only to project models."}
    if not doc.IsWorkshared:
        return {"status": "not_workshared", "document": doc.Title,
                "message": "This model is not workshared. It has no worksets to audit."}

    rules = inputs.get("rules") or ["links", "levels_grids", "workset1"]
    max_items = int(inputs.get("max_items") or 500)
    default_name = inputs.get("default_workset") or "Workset1"

    worksets = list(DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset))
    ws_by_int = {}
    ws_rows = []
    for ws in worksets:
        ws_by_int[ws.Id.IntegerValue] = ws
        count = (DB.FilteredElementCollector(doc)
                 .WherePasses(DB.ElementWorksetFilter(ws.Id, False))
                 .WhereElementIsNotElementType()
                 .GetElementCount())
        ws_rows.append({"workset_id": ws.Id.IntegerValue, "name": ws.Name,
                        "element_count": count, "is_open": ws.IsOpen,
                        "is_editable": ws.IsEditable, "owner": ws.Owner or ""})
    ws_rows.sort(key=lambda r: -r["element_count"])

    findings = {}
    targets = {}
    notes = []

    def add(el, rule, target):
        key = eid_int(el.Id)
        if key in findings:
            return
        cur = ws_by_int.get(el.WorksetId.IntegerValue)
        ok, why = movable(el)
        cat = el.Category.Name if el.Category else ""
        findings[key] = {
            "element_id": key, "category": cat, "name": el.Name or "", "rule": rule,
            "from_workset": cur.Name if cur else "(not a user workset)",
            "from_workset_id": el.WorksetId.IntegerValue,
            "to_workset": target.Name if target else "",
            "to_workset_id": target.Id.IntegerValue if target else None,
            "movable": ok and target is not None,
            "reason": why if not ok else ("" if target else "no target workset chosen"),
        }

    def rule_by_class(rule, cls_list, wanted, hints):
        target, cands = find_workset(worksets, wanted, hints)
        targets[rule] = {"target": target.Name if target else None, "candidates": cands}
        if target is None:
            notes.append("%s: no single target workset found. Candidates: %s. Pass the exact name."
                         % (rule, ", ".join(cands) if cands else "none"))
        for cls in cls_list:
            for el in DB.FilteredElementCollector(doc).OfClass(cls):
                if target is None or el.WorksetId != target.Id:
                    add(el, rule, target)

    if "links" in rules:
        rule_by_class("links", [DB.RevitLinkInstance], inputs.get("links_workset"), ["link"])
    if "levels_grids" in rules:
        rule_by_class("levels_grids", [DB.Level, DB.Grid],
                      inputs.get("levels_grids_workset"), ["level", "grid"])

    if "categories" in rules:
        cmap = inputs.get("category_map") or {}
        if not cmap:
            notes.append("categories: category_map is empty, so this rule found nothing.")
        for bic_name, ws_name in cmap.items():
            bic = getattr(DB.BuiltInCategory, bic_name, None)
            target, _ = find_workset(worksets, ws_name, [])
            if bic is None or target is None:
                notes.append("categories: skipped %s -> %s (unknown category or workset)."
                             % (bic_name, ws_name))
                continue
            col = (DB.FilteredElementCollector(doc).OfCategory(bic)
                   .WhereElementIsNotElementType())
            for el in col:
                if el.WorksetId != target.Id:
                    add(el, "categories", target)

    workset1 = None
    if "workset1" in rules:
        default_ws, _ = find_workset(worksets, default_name, [])
        if default_ws is None:
            workset1 = {"workset": default_name, "found": False}
        else:
            by_cat = {}
            col = (DB.FilteredElementCollector(doc)
                   .WherePasses(DB.ElementWorksetFilter(default_ws.Id, False))
                   .WhereElementIsNotElementType())
            for el in col:
                cat = el.Category
                if cat is None or cat.CategoryType != DB.CategoryType.Model:
                    continue
                by_cat[cat.Name] = by_cat.get(cat.Name, 0) + 1
            workset1 = {"workset": default_ws.Name, "found": True,
                        "model_elements": sum(by_cat.values()),
                        "by_category": sorted(by_cat.items(), key=lambda kv: -kv[1]),
                        "note": "Report only. Give a category_map and the 'categories' rule to move them."}

    items = sorted(findings.values(), key=lambda f: (f["rule"], f["category"], f["element_id"]))
    moves = [{"element_id": f["element_id"], "from_workset_id": f["from_workset_id"],
              "to_workset_id": f["to_workset_id"]} for f in items if f["movable"]]
    return {
        "status": "ok", "document": doc.Title, "is_workshared": True,
        "worksets": ws_rows, "rules": rules, "targets": targets,
        "finding_count": len(items), "movable_count": len(moves),
        "not_movable_count": len(items) - len(moves),
        "findings": items[:max_items], "findings_truncated": len(items) > max_items,
        "moves": moves, "workset1": workset1, "notes": notes,
    }

def ascii_safe(obj):
    r"""IronPython's json encoder in the agent runtime fails on non-ASCII text (for example
    "Café"). Escape every non-ASCII character as a literal \uXXXX sequence. Decode
    these sequences before you show a name to the user or write it to a CSV."""
    if isinstance(obj, dict):
        return dict((ascii_safe(k), ascii_safe(v)) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return [ascii_safe(x) for x in obj]
    try:
        is_text = isinstance(obj, basestring)
    except NameError:
        is_text = isinstance(obj, str)
    if is_text:
        return "".join(c if ord(c) < 128 else "\\u%04x" % ord(c) for c in obj)
    return obj


result = ascii_safe(main())
print("am-workset-audit: %s" % result.get("status"))

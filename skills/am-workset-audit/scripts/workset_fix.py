# -*- coding: utf-8 -*-
"""am-workset-audit, step 2: move elements to other worksets (run with run_modify).

ALWAYS run with dry_run=true first and show the result. Then run it for real with the
SAME inputs; the user approves or rejects it with Keep/Discard in Revit (policy "ask").

Runs on the pyRevit Agent Runtime, IronPython 2.7 (no f-strings) or CPython 3.
Adapted from Utopia5327/claude-plugin-for-revit-bim skills/workset-manager (MIT),
rewritten for pyRevit (no Dynamo TransactionManager / IN / OUT).

inputs:
  moves  list of {"element_id": int, "from_workset_id": int, "to_workset_id": int},
         copied unchanged from the "moves" list of workset_audit.py.
Each element is checked again at run time. An element that fails a check is skipped with
a reason; it never stops the other moves.
"""
from pyrevit.api import DB
from System import Int64

try:
    inputs
except NameError:
    inputs = {}
inputs = inputs or {}


def eid_int(element_id):
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def make_eid(number):
    # ElementId(Int64) exists in Revit 2024, 2025 and 2026; ElementId(Int32) is gone in 2026.
    return DB.ElementId(Int64(int(number)))


def main():
    if doc is None:
        return {"status": "no_active_document"}
    if doc.IsFamilyDocument or not doc.IsWorkshared:
        return {"status": "not_workshared",
                "message": "This model is not workshared. Nothing was moved."}
    moves = inputs.get("moves") or []
    if not moves:
        return {"status": "nothing_to_do", "message": "The moves list is empty."}

    user_ws = {}
    for ws in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset):
        user_ws[ws.Id.IntegerValue] = ws.Name

    moved = []
    skipped = []
    tx = DB.Transaction(doc, "Move elements to worksets")
    tx.Start()
    try:
        for m in moves:
            eid = int(m.get("element_id"))
            to_id = int(m.get("to_workset_id"))
            from_id = m.get("from_workset_id")

            def skip(reason):
                skipped.append({"element_id": eid, "reason": reason})

            if to_id not in user_ws:
                skip("target workset %s is not a user workset" % to_id)
                continue
            el = doc.GetElement(make_eid(eid))
            if el is None:
                skip("element no longer exists")
                continue
            cur = el.WorksetId.IntegerValue
            if cur == to_id:
                skip("already on %s" % user_ws[to_id])
                continue
            if from_id is not None and cur != int(from_id):
                skip("workset changed since the audit (now %s)" % user_ws.get(cur, cur))
                continue
            p = el.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
            if p is None or p.IsReadOnly:
                skip("workset is read-only (follows its host or is fixed)")
                continue
            if el.GroupId != DB.ElementId.InvalidElementId:
                skip("element is inside a group")
                continue
            if (DB.WorksharingUtils.GetCheckoutStatus(doc, el.Id)
                    == DB.CheckoutStatus.OwnedByOtherUser):
                skip("element is borrowed by another user")
                continue
            try:
                p.Set(to_id)
            except Exception as ex:
                skip("Revit refused the change: %s" % ex)
                continue
            moved.append({"element_id": eid_int(el.Id),
                          "category": el.Category.Name if el.Category else "",
                          "name": el.Name or "",
                          "from": user_ws.get(cur, str(cur)),
                          "to": user_ws[to_id]})
        if moved:
            tx.Commit()
        else:
            tx.RollBack()
    except Exception:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
        raise

    by_target = {}
    for m in moved:
        key = "%s -> %s" % (m["from"], m["to"])
        by_target[key] = by_target.get(key, 0) + 1
    return {"status": "ok", "requested": len(moves), "moved_count": len(moved),
            "skipped_count": len(skipped), "summary": by_target,
            "moved": moved, "skipped": skipped}

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
print("am-workset-fix: %s" % result.get("status"))

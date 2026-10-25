# -*- coding: utf-8 -*-
"""am-workset-audit, step 3: give borrowed elements back to central (run with run_query).

A dry run, or a Discard, rolls the workset moves back, but Revit keeps the edited elements
BORROWED from central, so teammates cannot edit them. workset_fix.py lists them in
"borrowed_by_this_run". This script releases them. It does not change the model, and Revit
never releases an element that has unsaved changes.

Same effect as Collaborate > Relinquish All Mine for ELEMENTS: Revit releases every element
the user has borrowed and not changed, not only the listed ones. Worksets the user owns stay
owned. Ask the user before you run it.

Runs on the pyRevit Agent Runtime, IronPython 2.7 or CPython 3. Checked live on a cloud model.

inputs:
  element_ids  list of int (optional), usually "borrowed_by_this_run". Reported before and
               after, so the user can see that they were released.
"""
from pyrevit.api import DB
from System import Int64

try:
    inputs
except NameError:
    inputs = {}
inputs = inputs or {}


def statuses(ids):
    return dict((str(i), str(DB.WorksharingUtils.GetCheckoutStatus(doc, DB.ElementId(Int64(int(i))))))
                for i in ids)


def main():
    if doc is None:
        return {"status": "no_active_document"}
    if doc.IsFamilyDocument or not doc.IsWorkshared:
        return {"status": "not_workshared", "message": "This model is not workshared. Nothing is borrowed."}
    ids = [int(i) for i in (inputs.get("element_ids") or [])]
    before = statuses(ids)
    opts = DB.RelinquishOptions(False)
    opts.CheckedOutElements = True
    # The returned RelinquishedItems listed 0 elements in a live test that did release one,
    # so the before/after checkout status of the listed ids is the evidence, not that list.
    DB.WorksharingUtils.RelinquishOwnership(doc, opts, DB.TransactWithCentralOptions())
    after = statuses(ids)
    still = [i for i in ids if after[str(i)] == "OwnedByCurrentUser"]
    return {"status": "ok" if not still else "partial",
            "listed_before": before, "listed_after": after,
            "still_borrowed": still,
            "message": ("All listed elements are released." if not still else
                        "Some listed elements are still borrowed (they may have unsaved changes).")}


result = main()
print("am-workset-relinquish: %s" % result.get("status"))

# -*- coding: utf-8 -*-
"""Worksharing ownership read for am-safe-change (issue #97). Read-only (run_query / --mode=query).

Use it twice in the skill:
- before the dry run, on the target ids, to find elements another user owns;
- after a kept or discarded run, on the target ids plus the categories of the
  dry run, to find what the current user now borrows.

inputs: {"ids": [123, 456],                       (target element ids)
         "categories": ["Views", "Text Notes"],   (optional: scan these for borrowed elements)
         "max_elements": 5000}                    (optional: scan limit, see am-revit-api-docs)
    ownership.py inputs --preview <preview.json> [--dryrun <dryrun.json>] writes this file.

result = {"document", "workshared": bool, "user", "escaped": bool,
          "elements": [{"id", "exists", "status", "owner", "updates", "category", "name"}],
          "scan": {"categories": [...], "missing_categories": [...], "checked", "partial"},
          "scan_borrowed": [{"id", "category", "name"}]}
status is the WorksharingUtils.GetCheckoutStatus name. owner is read with
GetWorksharingTooltipInfo only for OwnedByOtherUser. updates is the
GetModelUpdatesStatus name. The script never borrows, syncs or relinquishes.
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import sys

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"  # IronPython result encoder is ASCII-only (see read_sheets.py)

try:
    inputs
except NameError:
    inputs = {}
inputs = inputs or {}


def txt(s):
    if s is None:
        return ""
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


def eid_int(element_id):
    try:
        return int(element_id.Value)         # Revit 2024+
    except AttributeError:
        return int(element_id.IntegerValue)  # removed in Revit 2026


def make_id(i):
    try:
        import System
        return DB.ElementId(System.Int64(i))  # Revit 2024+ (2026 has only Int64)
    except Exception:
        return DB.ElementId(int(i))


# Compare with the enum members, not str(): the two engines print enums differently.
CHECKOUT = [(DB.CheckoutStatus.OwnedByOtherUser, "OwnedByOtherUser"),
            (DB.CheckoutStatus.OwnedByCurrentUser, "OwnedByCurrentUser"),
            (DB.CheckoutStatus.NotOwned, "NotOwned")]
UPDATES = [(DB.ModelUpdatesStatus.CurrentWithCentral, "CurrentWithCentral"),
           (DB.ModelUpdatesStatus.UpdatedInCentral, "UpdatedInCentral"),
           (DB.ModelUpdatesStatus.NotYetInCentral, "NotYetInCentral"),
           (DB.ModelUpdatesStatus.DeletedInCentral, "DeletedInCentral")]


def enum_name(value, table):
    for member, name in table:
        if value == member:
            return name
    return str(value)


def category_name(el):
    try:
        return txt(el.Category.Name) if el.Category is not None else ""
    except Exception:
        return ""


def element_name(el):
    try:
        return txt(el.Name)
    except Exception:
        return ""


def describe(i):
    eid = make_id(i)
    el = doc.GetElement(eid)
    if el is None:
        return {"id": i, "exists": False}
    status = enum_name(DB.WorksharingUtils.GetCheckoutStatus(doc, eid), CHECKOUT)
    owner = ""
    if status == "OwnedByOtherUser":
        try:
            owner = txt(DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, eid).Owner)
        except Exception:
            owner = ""
    try:
        updates = enum_name(DB.WorksharingUtils.GetModelUpdatesStatus(doc, eid), UPDATES)
    except Exception:
        updates = ""
    return {"id": i, "exists": True, "status": status, "owner": owner,
            "updates": updates, "category": category_name(el), "name": element_name(el)}


def scan(names, limit):
    """Elements in the named categories that the current user borrows."""
    wanted = set(names)
    cats = [c for c in doc.Settings.Categories if c.Name in wanted]
    found = set(c.Name for c in cats)
    borrowed, checked, partial = [], 0, False
    for cat in cats:
        for el in DB.FilteredElementCollector(doc).OfCategoryId(cat.Id):
            if checked >= limit:
                partial = True
                break
            checked += 1
            if DB.WorksharingUtils.GetCheckoutStatus(doc, el.Id) == DB.CheckoutStatus.OwnedByCurrentUser:
                borrowed.append({"id": eid_int(el.Id), "category": category_name(el),
                                 "name": element_name(el)})
        if partial:
            break
    return ({"categories": [txt(n) for n in sorted(found)],
             "missing_categories": [txt(n) for n in sorted(wanted - found)],
             "checked": checked, "partial": partial}, borrowed)


def main():
    if doc is None:
        return {"status": "no_active_document"}
    base = {"document": txt(doc.Title), "escaped": ESCAPE,
            "user": txt(doc.Application.Username)}
    if doc.IsFamilyDocument or not doc.IsWorkshared:
        base.update({"workshared": False, "elements": [], "scan_borrowed": [],
                     "scan": {"categories": [], "missing_categories": [],
                              "checked": 0, "partial": False}})
        return base
    ids = [int(i) for i in inputs.get("ids") or []]
    limit = int(inputs.get("max_elements") or 5000)
    info, borrowed = scan(inputs.get("categories") or [], limit)
    base.update({"workshared": True, "elements": [describe(i) for i in ids],
                 "scan": info, "scan_borrowed": borrowed})
    return base


result = main()

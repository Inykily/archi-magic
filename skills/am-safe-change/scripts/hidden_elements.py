"""Read or clear reviewed hide settings in the active Revit view."""
import hashlib
import json
import re

from System import Int64
from System.Collections.Generic import List
from System.Diagnostics import Stopwatch
from pyrevit.api import DB

import hidden_elements_preview as preview

CAP = 250


def checked_id(value, signed=False):
    pattern = r"^-?[1-9][0-9]{0,18}\Z" if signed else r"^[1-9][0-9]{0,18}\Z"
    if not re.match(pattern, str(value)) or abs(int(value)) > 2**63 - 1:
        raise ValueError("Use valid decimal Revit IDs.")
    return DB.ElementId(Int64(int(value)))


def key(identifier):
    return str(identifier.Value)


def ids(values, count, signed=False):
    if not isinstance(values, list) or len(values) > count:
        raise ValueError("The input scope is too large or invalid.")
    normalized = [key(checked_id(value, signed)) for value in values]
    if len(normalized) != len(set(normalized)):
        raise ValueError("Scope IDs must be distinct.")
    return sorted(normalized, key=int)


def available(operation):
    try:
        return operation()
    except Exception:
        return None


def modes(view):
    manager = view.TemporaryViewModes
    if manager is None:
        return None
    result = []
    for name in ("RevealHiddenElements", "TemporaryHideIsolate", "TemporaryViewProperties"):
        mode = getattr(DB.TemporaryViewMode, name)
        if manager.IsModeAvailable(mode) and manager.IsModeEnabled(mode):
            result.append(name)
    return result


def view_state(view, template):
    temporary = available(lambda: modes(view))
    independent = (view.GetPrimaryViewId().Value == -1 and not list(view.GetDependentViewIds()))
    placement = str(view.GetPlacementOnSheetStatus())
    ownership = None
    if doc.IsWorkshared:  # noqa: F821
        ownership = [available(lambda: str(DB.WorksharingUtils.GetCheckoutStatus(doc, view.Id))),  # noqa: F821
                     available(lambda: str(DB.WorksharingUtils.GetModelUpdatesStatus(doc, view.Id)))]  # noqa: F821
    own_ok = ownership is None or (ownership[0] in ("NotOwned", "OwnedByCurrentUser")
                                    and ownership[1] in ("CurrentWithCentral", "NotYetInCentral"))
    selection = __revit__.ActiveUIDocument.Selection.GetElementIds()  # noqa: F821
    if len(selection) > 1000:
        raise ValueError("Reduce the current UI selection before reviewing visibility.")
    return {"id": key(view.Id), "uid": str(view.UniqueId), "template_id": key(view.ViewTemplateId),
            "template_uid": str(template.UniqueId) if template is not None else None,
            "independent": independent, "placement": placement, "temporary": temporary,
            "selection": sorted([key(item) for item in selection], key=int),
            "ownership": ownership, "writable": (independent and placement == "NotPlaced" and temporary == []
                                                and own_ok and not doc.IsReadOnly)}  # noqa: F821


def controlled_ids(view, template):
    if view.ViewTemplateId.Value == -1:
        return []
    if template is None or not template.IsTemplate:
        return None
    return available(lambda: sorted(set(p.Value for p in template.GetTemplateParameterIds())
                                    - set(p.Value for p in template.GetNonControlledTemplateParameterIds())))


def origin(controls, group, current, template_value):
    if controls is None or current is None or group is None:
        return "unknown"
    if int(group) not in controls:
        return "view"
    return "template" if current == template_value else "unknown"


def category_state(view, template, controls, category):
    group = {"Model": DB.BuiltInParameter.VIS_GRAPHICS_MODEL,
             "Annotation": DB.BuiltInParameter.VIS_GRAPHICS_ANNOTATION}.get(str(category.CategoryType))
    hidden = available(lambda: bool(view.GetCategoryHidden(category.Id)))
    inherited = available(lambda: bool(template.GetCategoryHidden(category.Id))) if template is not None else None
    source = origin(controls, group, hidden, inherited)
    return {"id": key(category.Id), "hidden": hidden, "origin": source,
            "editable": bool(category.Parent is None and source == "view"
                             and available(lambda: view.CanCategoryBeHidden(category.Id)))}


def filter_flags(view, identifier):
    return [available(lambda: bool(view.GetIsFilterEnabled(identifier))),
            available(lambda: not bool(view.GetFilterVisibility(identifier)))]


def filter_data(view, template, controls):
    applied = list(view.GetOrderedFilters())
    if len(applied) > 32:
        raise ValueError("The active view has too many filters for a bounded report.")
    template_ids = available(lambda: {key(item) for item in template.GetOrderedFilters()}) if template is not None else set()
    rows, matchers = [], {}
    for identifier in applied:
        filter_id = key(identifier)
        item = doc.GetElement(identifier)  # noqa: F821
        flags = filter_flags(view, identifier)
        inherited = filter_flags(template, identifier) if template_ids is not None and filter_id in template_ids else None
        source = origin(controls, DB.BuiltInParameter.VIS_GRAPHICS_FILTERS,
                        flags if None not in flags else None, inherited)
        row = {"id": filter_id, "uid": str(item.UniqueId) if item is not None else None,
               "enabled": flags[0], "hidden": flags[1], "origin": source,
               "editable": bool(item is not None and source == "view" and flags[0] is True)}
        rows.append(row)
        if flags[0] is not True:
            continue
        if isinstance(item, DB.SelectionFilterElement):
            membership = available(lambda: item.GetElementIds())
            if membership is not None and len(membership) <= 5000:
                matchers[filter_id] = ("selection", {key(value) for value in membership}, None)
        elif isinstance(item, DB.ParameterFilterElement):
            def parameter_matcher():
                categories = {key(value) for value in item.GetCategories()}
                if not 1 <= len(categories) <= 32:
                    raise ValueError()
                return "parameter", categories, item.GetElementFilter()
            matcher = available(parameter_matcher)
            if matcher is not None:
                matchers[filter_id] = matcher
    return rows, matchers


def match(matcher, element):
    kind, keys, rule = matcher
    if kind == "selection":
        return key(element.Id) in keys
    return key(element.Category.Id) in keys and (
        rule is None or bool(rule.PassesFilter(doc, element.Id)))  # noqa: F821


def collect(category_keys, clock):
    found = set()
    for category in category_keys:
        collector = DB.FilteredElementCollector(doc).OfCategoryId(checked_id(category, True))  # noqa: F821
        for element in collector.WhereElementIsNotElementType():
            found.add(key(element.Id))
            if len(found) > CAP or clock.ElapsedMilliseconds >= 10000:
                raise ValueError("Scope is too large for a complete inventory. Narrow the read.")
    return found


def category_lookup(category):
    result = DB.Category.GetCategory(doc, checked_id(category, True))  # noqa: F821
    if result is None or result.Parent is not None or str(result.CategoryType) not in ("Model", "Annotation"):
        raise ValueError("Use supported top-level model or annotation category IDs.")
    return result


def category_tree(root):
    pending = [root]
    keys = []
    while pending:
        category = pending.pop()
        keys.append(key(category.Id))
        if len(keys) > 32:
            raise ValueError("The category has too many subcategories for bounded impact.")
        pending.extend(list(category.SubCategories))
    return keys


def scoped_elements(raw, clock, matchers):
    element_ids = ids(raw.get("element_ids", []), CAP)
    categories = ids(raw.get("category_ids", []), 5, True)
    for item in categories:
        category_lookup(item)
    if (bool(element_ids) == bool(categories)):
        raise ValueError("Choose explicit element IDs or discovery category IDs.")
    found = set(element_ids) if element_ids else collect(categories, clock)
    whole = raw.get("whole")
    impact = None
    if whole is not None:
        kind = whole["kind"]
        if kind not in ("category", "filter"):
            raise ValueError("Whole-view review needs one category or filter.")
        target = key(checked_id(whole["id"], kind == "category"))
        whole = {"kind": kind, "id": target}
        if kind == "category":
            impacted = collect(category_tree(category_lookup(target)), clock)
        else:
            if target not in matchers:
                raise ValueError("The applied enabled filter cannot be inventoried.")
            matcher = matchers[target]
            if matcher[0] == "selection":
                impacted = matcher[1]
            else:
                impacted = set()
                for item in collect(matcher[1], clock):
                    if clock.ElapsedMilliseconds >= 10000:
                        raise ValueError("The filter impact inventory exceeded its time budget.")
                    element = doc.GetElement(checked_id(item))  # noqa: F821
                    if element is None or element.Category is None:
                        raise ValueError("The filter impact inventory could not be resolved.")
                    if match(matcher, element):
                        impacted.add(item)
        found.update(impacted)
        impact = sorted(impacted, key=int)
    if len(found) > CAP:
        raise ValueError("The reviewed scope exceeds 250 element IDs.")
    return {"element_ids": element_ids, "category_ids": categories, "whole": whole}, found, impact


def snapshot(raw):
    if doc is None or doc.IsFamilyDocument or not doc.PathName:  # noqa: F821
        raise ValueError("Open a saved project.")
    view = doc.ActiveView  # noqa: F821
    if view is None or view.IsTemplate or not view.AreGraphicsOverridesAllowed():
        raise ValueError("Open a graphical view with visibility overrides.")
    clock = Stopwatch.StartNew()
    template = doc.GetElement(view.ViewTemplateId) if view.ViewTemplateId.Value != -1 else None  # noqa: F821
    view_info = view_state(view, template)
    controls = controlled_ids(view, template)
    filters, matchers = filter_data(view, template, controls)
    scope, selected, impact = scoped_elements(raw, clock, matchers)
    categories = {}
    if scope["whole"] and scope["whole"]["kind"] == "category":
        category = category_lookup(scope["whole"]["id"])
        categories[key(category.Id)] = category_state(view, template, controls, category)
    rows, ignored = [], []
    for element_id in sorted(selected, key=int):
        if clock.ElapsedMilliseconds >= 10000:
            raise ValueError("The visibility read exceeded its time budget. Narrow the scope.")
        element = doc.GetElement(checked_id(element_id))  # noqa: F821
        if (element is None or element.Category is None
                or isinstance(element, (DB.ElementType, DB.ImportInstance, DB.RevitLinkInstance))
                or str(element.Category.CategoryType) not in ("Model", "Annotation")
                or (element.ViewSpecific and element.OwnerViewId.Value != view.Id.Value)):
            ignored.append(element_id)
            continue
        category = element.Category
        category_path = []
        while category is not None:
            category_id = key(category.Id)
            if category_id in category_path or len(category_path) >= 8:
                raise ValueError("A category has unsupported parent nesting.")
            category_path.append(category_id)
            if category_id not in categories:
                categories[category_id] = category_state(view, template, controls, category)
            category = category.Parent
        matches, unknown = [], []
        for item in filters:
            if item["enabled"] is False:
                continue
            if clock.ElapsedMilliseconds >= 10000:
                raise ValueError("The visibility read exceeded its time budget. Narrow the scope.")
            matcher = matchers.get(item["id"])
            state = available(lambda: match(matcher, element)) if matcher is not None else None
            if state is True:
                matches.append(item["id"])
            elif state is None:
                unknown.append(item["id"])
        rows.append({"id": element_id, "uid": str(element.UniqueId), "category_path": category_path,
                     "direct": available(lambda: bool(element.IsHidden(view))),
                     "matched_filters": matches, "unknown_filters": unknown})
    if impact is not None and set(impact) & set(ignored):
        raise ValueError("Whole-view impact contains unsupported or unavailable elements.")
    return {"kind": "hidden-elements-snapshot", "view": view_info, "scope": scope, "impact": impact,
            "document": {"uid": str(doc.ProjectInformation.UniqueId),  # noqa: F821
                         "path_sha256": hashlib.sha256(doc.PathName.encode("utf-8")).hexdigest()},  # noqa: F821
            "elements": rows, "ignored": ignored, "controls": controls,
            "categories": [categories[item] for item in sorted(categories, key=int)], "filters": filters}


def encoded(data):
    raw = json.dumps(data, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("The visibility snapshot exceeds the result limit.")
    return {"status": "ok", "snapshot_json": raw}


def abort(txn, state=None):
    try:
        if state is None:
            state = txn.GetStatus()
        if state == DB.TransactionStatus.Started:
            state = txn.RollBack()
        if state == DB.TransactionStatus.RolledBack:
            return {"status": "stopped", "message": "The visibility change was rolled back."}
    except Exception:
        pass
    return {"status": "transaction_unresolved", "message": "Check the Revit transaction state before continuing."}


def apply(plan):
    if (plan.get("kind") != "change-preview" or plan.get("recipe") != "hidden-elements"
            or plan.get("blocked") is not False or any(item.get("blocking") for item in plan.get("warnings", []))):
        raise ValueError("Supply the approved, unblocked visibility preview.")
    fresh = snapshot(plan["basis"]["scope"])
    computed = preview.compute(fresh, plan["intent"])
    if fresh != plan["basis"] or computed["steps"] != plan["steps"] or computed["intent"] != plan["intent"]:
        raise ValueError("The reviewed visibility state or intent changed.")
    view = doc.ActiveView  # noqa: F821
    txn = DB.Transaction(doc, "Clear reviewed visibility hides")  # noqa: F821
    state = txn.Start()
    if state != DB.TransactionStatus.Started:
        return abort(txn, state)
    try:
        kind = plan["intent"]["kind"]
        selected = plan["intent"]["ids"]
        if kind == "element":
            targets = List[DB.ElementId]()
            for item in selected:
                identifier = checked_id(item)
                if not doc.GetElement(identifier).IsHidden(view):  # noqa: F821
                    raise ValueError("The direct hide changed.")
                targets.Add(identifier)
            view.UnhideElements(targets)
        elif kind == "category":
            identifier = checked_id(selected[0], True)
            if not view.CanCategoryBeHidden(identifier) or not view.GetCategoryHidden(identifier):
                raise ValueError("The category hide changed.")
            view.SetCategoryHidden(identifier, False)
        else:
            identifier = checked_id(selected[0])
            if (selected[0] not in {key(item) for item in view.GetOrderedFilters()}
                    or filter_flags(view, identifier) != [True, True]):
                raise ValueError("The applied filter hide changed.")
            view.SetFilterVisibility(identifier, True)
        doc.Regenerate()  # noqa: F821
        after = snapshot(plan["basis"]["scope"])
        preview.check_after(plan, after)
        result = encoded(after)
        state = txn.Commit()
        return result if state == DB.TransactionStatus.Committed else abort(txn, state)
    except Exception:
        return abort(txn)


try:
    if inputs.get("mode", "read") == "read":  # noqa: F821
        result = encoded(snapshot(inputs["scope"]))  # noqa: F821
    elif inputs["mode"] == "apply":  # noqa: F821
        result = apply(inputs["plan"])  # noqa: F821
    else:
        raise ValueError("Choose read or apply.")
except ValueError as error:
    result = {"status": "stopped", "message": str(error)}
except Exception:
    result = {"status": "stopped", "message": "Revit could not establish the requested visibility scope."}

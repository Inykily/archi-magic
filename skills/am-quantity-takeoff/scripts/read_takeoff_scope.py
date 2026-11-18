# -*- coding: utf-8 -*-
"""List the host elements of a material takeoff scope and split them into batches.

Read-only. Run with run_query. It never calls GetMaterialIds or reads geometry, so it
stays fast on a large model. Each batch is the element_ids input of
am-material-audit/scripts/read_material_quantities.py (1 to 500 IDs).

inputs (all optional):
  categories             list of BuiltInCategory names, for example ["OST_Walls", "OST_Floors"].
                         Default: every model category that has material quantities.
  level_ids              list of level IDs as decimal strings. Default: all levels and no level.
  phase_id               phase ID as a decimal string. Keep elements whose status in that phase
                         is in phase_statuses.
  phase_statuses         subset of ["New", "Existing", "Demolished", "Temporary"].
                         Default with phase_id: ["New", "Existing"].
  include_secondary_options  true keeps elements in secondary design options. Default false.
  batch_size             1 to 500. Default 200.
"""

import hashlib
import json
import re
import time

from pyrevit.api import DB
from System import Int32, Int64

try:
    TEXT = basestring  # noqa: F821 (IronPython 2.7)
    WHOLE = (int, long)  # noqa: F821
except NameError:
    TEXT = str
    WHOLE = (int,)

MAX_ELEMENTS = 20000
MAX_BATCHES = 400
MAX_BATCH_SIZE = 500
DEFAULT_BATCH_SIZE = 200
TIME_LIMIT_S = 10.0
PAYLOAD_LIMIT = 1024 * 1024
PHASE_STATUSES = ("New", "Existing", "Demolished", "Temporary")
NO_LEVEL = -1


class InputError(ValueError):
    """The request cannot define a scope."""


def eid(element_id):
    return int(element_id.Value if hasattr(element_id, "Value") else element_id.IntegerValue)


def make_id(value):
    id_type = Int64 if hasattr(DB.ElementId, "Value") else Int32
    return DB.ElementId(id_type(value))


def decimal_id(value):
    if not isinstance(value, TEXT) or not re.match(r"[1-9][0-9]{0,18}\Z", value) or int(value) >= 2 ** 63:
        raise InputError("Use positive decimal element IDs as text, for example \"123\".")
    return int(value)


def read_request(inputs):
    inputs = inputs or {}
    known = {"categories", "level_ids", "phase_id", "phase_statuses", "include_secondary_options", "batch_size"}
    if not isinstance(inputs, dict) or set(inputs) - known:
        raise InputError("Unknown input. Use: " + ", ".join(sorted(known)) + ".")
    request = {"categories": None, "level_ids": None, "phase_id": None, "phase_statuses": None,
               "include_secondary_options": False, "batch_size": DEFAULT_BATCH_SIZE}
    names = inputs.get("categories")
    if names is not None:
        if not isinstance(names, list) or not 1 <= len(names) <= 60:
            raise InputError("Give 1 to 60 category names.")
        for name in names:
            if not isinstance(name, TEXT) or not re.match(r"OST_[A-Za-z0-9_]{1,80}\Z", name):
                raise InputError("Use BuiltInCategory names, for example OST_Walls.")
        if len(set(names)) != len(names):
            raise InputError("A category name is repeated.")
        request["categories"] = sorted(names)
    levels = inputs.get("level_ids")
    if levels is not None:
        if not isinstance(levels, list) or not 1 <= len(levels) <= 200:
            raise InputError("Give 1 to 200 level IDs.")
        parsed = [decimal_id(value) for value in levels]
        if len(set(parsed)) != len(parsed):
            raise InputError("A level ID is repeated.")
        request["level_ids"] = sorted(parsed)
    if inputs.get("phase_id") is not None:
        request["phase_id"] = decimal_id(inputs["phase_id"])
        statuses = inputs.get("phase_statuses", ["New", "Existing"])
        if (not isinstance(statuses, list) or not statuses or len(set(statuses)) != len(statuses)
                or any(status not in PHASE_STATUSES for status in statuses)):
            raise InputError("Use phase_statuses from: " + ", ".join(PHASE_STATUSES) + ".")
        request["phase_statuses"] = [status for status in PHASE_STATUSES if status in statuses]
    elif inputs.get("phase_statuses") is not None:
        raise InputError("phase_statuses needs phase_id.")
    option = inputs.get("include_secondary_options", False)
    if option not in (True, False):
        raise InputError("include_secondary_options must be true or false.")
    request["include_secondary_options"] = option
    size = inputs.get("batch_size", DEFAULT_BATCH_SIZE)
    if isinstance(size, bool) or not isinstance(size, WHOLE) or not 1 <= size <= MAX_BATCH_SIZE:
        raise InputError("batch_size must be a whole number from 1 to 500.")
    request["batch_size"] = size
    return request


def quantity_category(category):
    return (category is not None and category.Parent is None and category.HasMaterialQuantities
            and category.CategoryType == DB.CategoryType.Model)


def scope_categories(document, names):
    if names is None:
        found = [category for category in document.Settings.Categories if quantity_category(category)]
    else:
        found = []
        for name in names:
            builtin = getattr(DB.BuiltInCategory, name, None)
            category = DB.Category.GetCategory(document, builtin) if builtin is not None else None
            if category is None:
                raise InputError("The model has no category " + name + ".")
            if not quantity_category(category):
                raise InputError(name + " is not a model category with material quantities.")
            found.append(category)
    return sorted(found, key=lambda category: eid(category.Id))


def element_level(document, element, cache):
    """Match read_material_quantities.py: a level that does not resolve counts as no level."""
    level_id = eid(element.LevelId) if element.LevelId is not None else NO_LEVEL
    if level_id <= 0:
        return NO_LEVEL, None
    if level_id not in cache:
        level = document.GetElement(element.LevelId)
        cache[level_id] = None if level is None else level.Name
    if cache[level_id] is None:
        return NO_LEVEL, None
    return level_id, cache[level_id]


def project_stamp(document):
    path = getattr(document, "PathName", "")
    info = getattr(document, "ProjectInformation", None)
    if not path or info is None:
        return None
    return {"uid": str(info.UniqueId), "path_sha256": hashlib.sha256(path.encode("utf-8")).hexdigest()}


def scope_digest(batches):
    joined = ",".join(value for batch in batches for value in batch["element_ids"])
    return hashlib.sha256(joined.encode("ascii")).hexdigest()


def read_scope(document, inputs, max_elements=MAX_ELEMENTS, time_limit=TIME_LIMIT_S):
    request = read_request(inputs)
    started = time.time()
    levels = None
    if request["level_ids"] is not None:
        levels = set()
        for level_id in request["level_ids"]:
            if not isinstance(document.GetElement(make_id(level_id)), DB.Level):
                raise InputError("Level ID " + str(level_id) + " is not a level.")
            levels.add(level_id)
    phase = None
    wanted = []
    if request["phase_id"] is not None:
        phase = document.GetElement(make_id(request["phase_id"]))
        if not isinstance(phase, DB.Phase):
            raise InputError("phase_id is not a phase.")
        wanted = [getattr(DB.ElementOnPhaseStatus, name) for name in request["phase_statuses"]]
    categories = scope_categories(document, request["categories"])

    issues = []
    excluded = {"outside_levels": 0, "outside_phase": 0, "secondary_design_option": 0}
    records = []
    category_names = {}
    level_names = {}
    level_cache = {}
    stopped = False
    for category in categories:
        if stopped:
            break
        category_id = eid(category.Id)
        category_names[category_id] = category.Name
        collector = DB.FilteredElementCollector(document).OfCategoryId(category.Id).WhereElementIsNotElementType()
        for element in collector:
            if time.time() - started > time_limit:
                issues.append({"reason": "scope_read_budget_exceeded"})
                stopped = True
                break
            level_id, level_name = element_level(document, element, level_cache)
            if levels is not None and level_id not in levels:
                excluded["outside_levels"] += 1
                continue
            option = element.DesignOption
            if option is not None and not option.IsPrimary and not request["include_secondary_options"]:
                excluded["secondary_design_option"] += 1
                continue
            if phase is not None:
                status = element.GetPhaseStatus(phase.Id)
                if not any(status == value for value in wanted):
                    excluded["outside_phase"] += 1
                    continue
            if len(records) >= max_elements:
                issues.append({"reason": "element_limit_exceeded", "limit": max_elements})
                stopped = True
                break
            level_names[level_id] = level_name
            records.append((category_id, level_id, eid(element.Id)))

    records.sort()
    size = request["batch_size"]
    batches = []
    if -(-len(records) // size) > MAX_BATCHES:
        issues.append({"reason": "too_many_batches", "limit": MAX_BATCHES})
    else:
        for start in range(0, len(records), size):
            chunk = records[start:start + size]
            batches.append({"index": len(batches) + 1,
                            "element_ids": [str(record[2]) for record in chunk],
                            "groups": [list(pair) for pair in sorted(set((record[0], record[1])
                                                                          for record in chunk))]})
    groups = {}
    for category_id, level_id, _ in records:
        groups[(category_id, level_id)] = groups.get((category_id, level_id), 0) + 1
    project = project_stamp(document)
    if project is None:
        issues.append({"reason": "project_not_saved"})
    if not records and not issues:
        issues.append({"reason": "no_elements_in_scope"})
    return {
        "kind": "takeoff-scope",
        "status": "incomplete" if issues else "ready",
        "project": project,
        "request": request,
        "element_count": len(records),
        "excluded": excluded,
        "categories": [{"id": key, "name": category_names[key],
                        "elements": sum(count for (cat, _), count in groups.items() if cat == key)}
                       for key in sorted(category_names)],
        "levels": [{"id": key, "name": level_names[key],
                    "elements": sum(count for (_, lev), count in groups.items() if lev == key)}
                   for key in sorted(level_names)],
        "groups": [{"category_id": cat, "level_id": lev, "elements": groups[(cat, lev)]}
                   for cat, lev in sorted(groups)],
        "phases": [{"id": eid(item.Id), "name": item.Name} for item in document.Phases],
        "batches": batches,
        "scope_sha256": scope_digest(batches),
        "issues": issues,
        "not_covered": ["linked models", "paint", "element types", "elements of other categories"],
    }


if doc is None or doc.IsFamilyDocument:  # noqa: F821 (doc and inputs come from the runtime)
    result = {"error": "no_project_document", "message": "Open a Revit project first."}
else:
    try:
        report = read_scope(doc, inputs)  # noqa: F821
        payload = json.dumps(report, ensure_ascii=True, allow_nan=False, sort_keys=True)
        if len(payload) > PAYLOAD_LIMIT:
            report.update(status="incomplete", batches=[], scope_sha256=scope_digest([]),
                          issues=report["issues"] + [{"reason": "scope_payload_budget_exceeded"}])
            payload = json.dumps(report, ensure_ascii=True, allow_nan=False, sort_keys=True)
        result = {"payload": payload}
    except InputError as exc:
        result = {"error": "invalid_input", "message": str(exc)}

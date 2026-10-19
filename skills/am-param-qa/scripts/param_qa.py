# -*- coding: utf-8 -*-
"""am-param-qa: read-only parameter completeness check for the pyRevit Agent Runtime.

Submit with the pyrevit MCP tool run_query, passing `inputs`
(or `pyrevit agent run <this file> --mode=query --inputs=<json>`).
IronPython 2.7 compatible: no f-strings, no type hints, no print kwargs.
The script changes nothing and writes no files.

inputs (all optional):
  {"rules": {"OST_Doors": ["Mark", "Fire Rating", "Comments"],
             "OST_Rooms": ["Name", "Number", "Department"]},
   "max_rows": 200,      # offender rows returned (the counts always cover all elements)
   "max_ids": 1000}      # offender ids returned per category

For each element and each required parameter, the script looks on the
instance first, then on its type. A parameter is:
  MISSING - not on the instance and not on the type (not bound to this category)
  EMPTY   - present but has no value, or a blank text value
A numeric 0 that the user entered counts as filled (Parameter.HasValue is True).
"""
import sys

from pyrevit.api import DB

try:
    INPUTS = inputs  # noqa: F821  (injected by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}

DEFAULT_RULES = {
    "OST_Doors": ["Mark", "Fire Rating", "Comments"],
    "OST_Rooms": ["Name", "Number", "Department"],
}
RULES = INPUTS.get("rules") or DEFAULT_RULES
MAX_ROWS = int(INPUTS.get("max_rows", 200))
MAX_IDS = int(INPUTS.get("max_ids", 1000))

# Names that map to built-in parameters, so the check works in any Revit language.
# Each name is tried as a built-in parameter first, then by its display name.
ALIASES = {
    "mark": ["ALL_MODEL_MARK"],
    "comments": ["ALL_MODEL_INSTANCE_COMMENTS"],
    "type mark": ["ALL_MODEL_TYPE_MARK"],
    "fire rating": ["DOOR_FIRE_RATING", "FIRE_RATING"],
    "name": ["ROOM_NAME"],
    "number": ["ROOM_NUMBER"],
    "department": ["ROOM_DEPARTMENT"],
}

IRONPYTHON = sys.platform == "cli"


def jsonable(value):
    """Keep non-ASCII names intact through the runtime's json.dumps on IronPython 2.7.
    See am-model-health/scripts/model_health.py for the reason."""
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if IRONPYTHON and isinstance(value, basestring):  # noqa: F821
        if any(ord(c) > 127 for c in value):
            return value.encode("utf-8").decode("latin-1")
    return value


def eid(element_id):
    """ElementId -> int. Revit 2024+ has .Value; 2023 and older only .IntegerValue."""
    if hasattr(element_id, "Value"):
        return int(element_id.Value)
    return int(element_id.IntegerValue)


def find_param(element, name):
    if element is None:
        return None
    for bip_name in ALIASES.get(name.strip().lower(), []):
        bip = getattr(DB.BuiltInParameter, bip_name, None)
        if bip is None:
            continue
        p = element.get_Parameter(bip)
        if p is not None:
            return p
    return element.LookupParameter(name)


def is_empty(p):
    if not p.HasValue:
        return True
    if p.StorageType == DB.StorageType.String:
        v = p.AsString()
        return v is None or not v.strip()
    if p.StorageType == DB.StorageType.ElementId:
        return eid(p.AsElementId()) < 0
    return False


def label_for(element):
    for bip in (DB.BuiltInParameter.ALL_MODEL_MARK, DB.BuiltInParameter.ROOM_NUMBER):
        p = element.get_Parameter(bip)
        if p is not None and p.HasValue and p.AsString():
            return p.AsString()
    try:
        return element.Name
    except Exception:
        return ""


if doc is None or doc.IsFamilyDocument:  # noqa: F821
    result = {"error": "no_project_document",
              "message": "Open a Revit project (.rvt), not a family, then run again."}
else:
    summary = []
    rows = []
    unknown = []
    total_offenders = 0
    for cat_key in sorted(RULES.keys()):
        bic = getattr(DB.BuiltInCategory, cat_key, None)
        if bic is None:
            unknown.append(cat_key)
            continue
        required = RULES[cat_key]
        col = (DB.FilteredElementCollector(doc)  # noqa: F821
               .OfCategory(bic).WhereElementIsNotElementType())
        elements = list(col)
        cat_name = cat_key
        by_param = dict((p, {"missing": 0, "empty": 0, "on_type": 0}) for p in required)
        offender_ids = []
        passed = 0
        for el in elements:
            if el.Category is not None:
                cat_name = el.Category.Name
            el_type = doc.GetElement(el.GetTypeId())  # noqa: F821
            problems = []
            for pname in required:
                p = find_param(el, pname)
                level = "instance"
                if p is None or (is_empty(p) and el_type is not None
                                 and find_param(el_type, pname) is not None):
                    tp = find_param(el_type, pname)
                    if tp is not None:
                        p = tp
                        level = "type"
                if p is None:
                    by_param[pname]["missing"] += 1
                    problems.append(pname + ": MISSING")
                elif is_empty(p):
                    by_param[pname]["empty"] += 1
                    problems.append("%s: EMPTY (%s)" % (pname, level))
                elif level == "type":
                    by_param[pname]["on_type"] += 1
            if problems:
                offender_ids.append(eid(el.Id))
                if len(rows) < MAX_ROWS:
                    rows.append({"id": eid(el.Id), "category": cat_name,
                                 "label": label_for(el), "problems": problems})
            else:
                passed += 1
        total = len(elements)
        failed = total - passed
        total_offenders += failed
        summary.append({
            "category": cat_name,
            "key": cat_key,
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": (round(100.0 * passed / total, 1) if total else None),
            "by_param": by_param,
            "offender_ids": offender_ids[:MAX_IDS],
        })
    result = jsonable({
        "model": doc.Title,  # noqa: F821
        "rules": RULES,
        "unknown_categories": unknown,
        "summary": summary,
        "total_offenders": total_offenders,
        "rows": rows,
        "rows_truncated": total_offenders > len(rows),
    })
    print("am-param-qa: %d categories, %d elements with problems" % (len(summary), total_offenders))

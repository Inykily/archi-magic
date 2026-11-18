# -*- coding: utf-8 -*-
"""READ step for the instance-flag recipe (issue #250). Read-only (run_query).

inputs: {"categories": ["OST_Walls"],          BuiltInCategory names
         "parameter": "QA Flag",               the instance text parameter for the flag
         "value_parameter": "Unconnected Height",  instance value to check (a length)
         "limit_parameter": "Limiting Height",     the limit
         "limit_on": "type"}                    "type" (default) or "instance"

For each instance: amount = value - limit (feet) when the value is more
than the limit, else null. An instance with no value or no limit gets
amount null and "check": "no value" or "no limit". The script never
changes the model.

result = {"document", "parameter", "parameter_exists", "categories",
          "workshared", "escaped",
          "elements": [{"id", "category", "name", "amount", "value", "limit",
                        "check", "current", "status", "owner", "in_group"}]}
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import sys

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"  # IronPython result encoder is ASCII-only (see read_sheets.py)
MAX_ELEMENTS = 5000  # the query budget in am-revit-api-docs
TOLERANCE = 1e-6


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


def number(element, name):
    if element is None or not name:
        return None
    param = element.LookupParameter(name)
    if param is None or not param.HasValue or param.StorageType != DB.StorageType.Double:
        return None
    return float(param.AsDouble())


def parameter_bound(document, name):
    it = document.ParameterBindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        if it.Key is not None and it.Key.Name == name:
            return True
    return False


categories = inputs.get("categories") or []  # noqa: F821
parameter = inputs.get("parameter")  # noqa: F821
value_name = inputs.get("value_parameter")  # noqa: F821
limit_name = inputs.get("limit_parameter")  # noqa: F821
limit_on = inputs.get("limit_on") or "type"  # noqa: F821
if not categories or not parameter or not value_name or not limit_name:
    raise ValueError("inputs needs categories, parameter, value_parameter and limit_parameter.")

workshared = bool(doc.IsWorkshared)  # noqa: F821
rows = []
for cat_name in categories:
    bic = getattr(DB.BuiltInCategory, cat_name)
    collector = DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType()  # noqa: F821
    for el in collector:
        if len(rows) >= MAX_ELEMENTS:
            raise ValueError("More than %d elements. Narrow the scope first." % MAX_ELEMENTS)
        value = number(el, value_name)
        holder = el if limit_on == "instance" else doc.GetElement(el.GetTypeId())  # noqa: F821
        limit = number(holder, limit_name)
        amount = None
        check = "ok"
        if value is None:
            check = "no value"
        elif limit is None:
            check = "no limit"
        elif value - limit > TOLERANCE:
            amount = value - limit
            check = "over"
        flag = el.LookupParameter(parameter)
        status, owner = "NotOwned", ""
        if workshared:
            status = str(DB.WorksharingUtils.GetCheckoutStatus(doc, el.Id))  # noqa: F821
            if status == "OwnedByOtherUser":
                owner = txt(DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, el.Id).Owner)  # noqa: F821
        try:
            name = txt(el.Name)
        except Exception:
            name = ""
        rows.append({"id": id_int(el.Id), "category": txt(el.Category.Name) if el.Category else "",
                     "name": name, "amount": amount, "value": value, "limit": limit,
                     "check": check,
                     "current": txt(flag.AsString()) if flag is not None else None,
                     "status": status, "owner": owner,
                     "in_group": id_int(el.GroupId) > 0})

result = {"document": txt(doc.Title), "parameter": txt(parameter),  # noqa: F821
          "parameter_exists": parameter_bound(doc, parameter),  # noqa: F821
          "categories": categories, "workshared": workshared,
          "elements": rows, "escaped": ESCAPE}

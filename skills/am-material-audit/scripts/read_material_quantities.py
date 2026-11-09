# -*- coding: utf-8 -*-
"""Read material quantities for explicitly selected Revit elements via run_query."""

import json
import math

from pyrevit.api import DB
from System import Int32, Int64


def eid(element_id):
    return int(element_id.Value if hasattr(element_id, "Value") else element_id.IntegerValue)


def selected_ids(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 500:
        raise ValueError("Pass 1 to 500 element IDs in inputs.element_ids.")
    selected = []
    seen = set()
    for value in values:
        key = int(value)
        if isinstance(value, (bool, float)) or key <= 0 or key > 9223372036854775807:
            raise ValueError("Element IDs must be positive whole numbers.")
        if key not in seen:
            seen.add(key)
            selected.append(key)
    return selected


def takeoff(document, ids):
    rows = {}
    issues = []
    for element_id in ids:
        try:
            id_type = Int64 if hasattr(DB.ElementId, "Value") else Int32
            element = document.GetElement(DB.ElementId(id_type(element_id)))
            if element is None:
                issues.append({"element_id": element_id, "reason": "element_not_found"})
                continue
            category = element.Category
            if category is None or not category.HasMaterialQuantities:
                issues.append({"element_id": element_id, "reason": "category_has_no_material_quantities"})
                continue
            level = document.GetElement(element.LevelId)
            if level is None:
                issues.append({"element_id": element_id, "reason": "level_unknown"})
            material_ids = list(element.GetMaterialIds(False))
            if not material_ids:
                issues.append({"element_id": element_id, "reason": "no_geometry_materials"})
            for material_id in material_ids:
                try:
                    material = document.GetElement(material_id)
                    if material is None:
                        issues.append({"element_id": element_id, "material_id": eid(material_id),
                                       "reason": "material_not_found"})
                        continue
                    area = DB.UnitUtils.ConvertFromInternalUnits(
                        element.GetMaterialArea(material_id, False), DB.UnitTypeId.SquareMeters)
                    volume = DB.UnitUtils.ConvertFromInternalUnits(
                        element.GetMaterialVolume(material_id), DB.UnitTypeId.CubicMeters)
                    if any(math.isnan(value) or math.isinf(value) or value < 0 for value in (area, volume)):
                        raise ValueError("Invalid quantity.")
                    level_id = eid(level.Id) if level is not None else -1
                    group = eid(category.Id), level_id, eid(material_id)
                    row = rows.setdefault(group, {
                        "category": category.Name, "category_id": group[0],
                        "level": level.Name if level is not None else None, "level_id": level_id,
                        "material": material.Name, "material_id": group[2],
                        "area_m2": 0.0, "volume_m3": 0.0,
                    })
                    row["area_m2"] += area
                    row["volume_m3"] += volume
                except Exception as exc:
                    issues.append({"element_id": element_id, "material_id": eid(material_id),
                                   "reason": "quantity_read_failed", "error_type": type(exc).__name__})
        except Exception as exc:
            issues.append({"element_id": element_id, "reason": "element_read_failed",
                           "error_type": type(exc).__name__})
    return {"requested_elements": len(ids), "status": "incomplete" if issues else "reported",
            "rows": [rows[key] for key in sorted(rows)], "issues": issues,
            "scope": "selected host elements, geometry and compound layers only"}


if doc is None or doc.IsFamilyDocument:
    result = {"error": "Open a Revit project first."}
else:
    result = {"payload": json.dumps(takeoff(doc, selected_ids(inputs.get("element_ids"))), ensure_ascii=True)}

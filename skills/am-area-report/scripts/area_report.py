# -*- coding: utf-8 -*-
"""am-area-report: READ-ONLY room and area report (run with run_query).

Runs on the pyRevit Agent Runtime, IronPython 2.7 (no f-strings) or CPython 3.
Adapted from Utopia5327/claude-plugin-for-revit-bim skills/analyze-rooms (MIT),
rewritten for pyRevit (no Dynamo DocumentManager / IN / OUT). It writes no files:
Claude writes the CSV from "header" + "rows".

inputs (all optional):
  group_by        room parameter to group by. Default "Department".
  program_csv     CSV text "key,target_area" (a header row is allowed) to compare with.
  program_key     "group" (match the group_by value, default) or "name" (match room name).
  program_units   units of the targets: "display" (default), "m2" or "ft2".
  tolerance_pct   +/- percent that still counts as "OK". Default 5.
  include_area_plans  true (default): also total Area elements by area scheme and level.
"""
from pyrevit.api import DB

try:
    inputs
except NameError:
    inputs = {}
inputs = inputs or {}

FT2_TO_M2 = 0.09290304


def eid_int(element_id):
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def display_units():
    """(converter, label, ok). Uses the project's area display units when readable."""
    try:
        unit_id = doc.GetUnits().GetFormatOptions(DB.SpecTypeId.Area).GetUnitTypeId()
        label = DB.LabelUtils.GetLabelForUnit(unit_id)

        def conv(ft2):
            return DB.UnitUtils.ConvertFromInternalUnits(ft2, unit_id)
        return conv, label, True
    except Exception:
        return (lambda ft2: ft2 * FT2_TO_M2), "Square meters", False


def param_text(el, name):
    if name.lower() == "department":
        p = el.get_Parameter(DB.BuiltInParameter.ROOM_DEPARTMENT)
    else:
        p = el.LookupParameter(name)
    if p is None:
        return None
    if p.StorageType == DB.StorageType.String:
        return p.AsString() or ""
    return p.AsValueString() or ""


def room_status(room, opts):
    """placed / not_placed / not_enclosed / redundant (same test as Revit's room warnings)."""
    if room.Area > 0:
        return "placed"
    if room.Location is None:
        return "not_placed"
    segs = room.GetBoundarySegments(opts)
    if segs is None or len(list(segs)) == 0:
        return "not_enclosed"
    return "redundant"


def room_elements():
    return (DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms)
            .WhereElementIsNotElementType())


def occupancy_snapshot():
    import json
    import math
    import re
    from System import Int64
    from System.Diagnostics import Stopwatch

    def element_id(value, expected):
        if not re.match(r"^[1-9][0-9]{0,18}\Z", str(value)) or int(value) > 2**63 - 1:
            raise ValueError()
        element = doc.GetElement(DB.ElementId(Int64(int(value))))
        if not isinstance(element, expected):
            raise ValueError()
        return str(eid_int(element.Id))

    try:
        level_values = inputs.get("level_ids")
        if not isinstance(level_values, list) or not 1 <= len(level_values) <= 20:
            raise ValueError()
        levels = [element_id(value, DB.Level) for value in level_values]
        phase = element_id(inputs.get("phase_id"), DB.Phase)
        if len(set(levels)) != len(levels):
            raise ValueError()
        parameter_name = inputs.get("occupancy_parameter")
        if parameter_name is not None and (
                not hasattr(parameter_name, "strip") or not parameter_name.strip() or len(parameter_name) > 80):
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        return {"status": "invalid_occupancy_scope"}

    clock = Stopwatch.StartNew()
    if DB.FilteredElementCollector(doc).OfClass(DB.DesignOption).GetElementCount():
        return {"status": "design_options_require_review"}
    options = DB.SpatialElementBoundaryOptions()
    selected = set(levels)
    rows = []
    for count, room in enumerate(room_elements(), 1):
        if count > 20000 or clock.ElapsedMilliseconds >= 10000:
            return {"status": "occupancy_scan_limit"}
        level_id = str(eid_int(room.LevelId))
        if int(level_id) > 0 and level_id not in selected:
            continue
        phase_parameter = room.get_Parameter(DB.BuiltInParameter.ROOM_PHASE_ID)
        if phase_parameter is None or phase_parameter.StorageType != DB.StorageType.ElementId:
            return {"status": "room_phase_unavailable"}
        room_phase = str(eid_int(phase_parameter.AsElementId()))
        if int(room_phase) <= 0:
            return {"status": "room_phase_unavailable"}
        if room_phase != phase:
            continue
        if level_id not in selected or room.DesignOption is not None:
            return {"status": "room_scope_unavailable"}
        if len(rows) >= 3000:
            return {"status": "occupancy_scan_limit"}
        if parameter_name is None:
            parameter = room.get_Parameter(DB.BuiltInParameter.ROOM_OCCUPANCY)
        else:
            matches = list(room.GetParameters(parameter_name))
            parameter = matches[0] if len(matches) == 1 else None
        use = parameter.AsString() if parameter is not None and parameter.StorageType == DB.StorageType.String else None
        if use is not None and len(use) > 120:
            use = None
        area = float(room.Area)
        if math.isnan(area) or math.isinf(area) or area < 0:
            return {"status": "room_area_unavailable"}
        rows.append({"id": str(eid_int(room.Id)), "level_id": level_id,
                     "status": room_status(room, options), "occupancy": use, "area_ft2": area})
    if clock.ElapsedMilliseconds >= 10000:
        return {"status": "occupancy_scan_limit"}
    payload = {"kind": "occupancy-room-snapshot", "phase_id": phase, "level_ids": levels,
               "area_basis": "net_room", "room_count": len(rows), "rooms": rows}
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > 2 * 1024 * 1024:
        return {"status": "occupancy_snapshot_size_limit"}
    return {"status": "ok", "snapshot_json": encoded, "room_count": len(rows)}


def add(bucket, key, ft2, conv):
    b = bucket.setdefault(key, {"count": 0, "area_ft2": 0.0})
    b["count"] += 1
    b["area_ft2"] += ft2


def finish(bucket, conv):
    out = []
    for key in sorted(bucket.keys()):
        b = bucket[key]
        out.append({"key": key, "count": b["count"],
                    "area_display": round(conv(b["area_ft2"]), 2),
                    "area_m2": round(b["area_ft2"] * FT2_TO_M2, 2),
                    "area_ft2": round(b["area_ft2"], 2)})
    return out


def parse_program(text):
    """CSV text -> [(key, target)]. Uses the first and last column, so quoted keys with
    commas and quoted numbers such as "1,200" work. A header row is skipped."""
    import csv
    rows = []
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    for parts in csv.reader(lines):
        parts = [p.strip() for p in parts]
        if len(parts) < 2:
            continue
        try:
            rows.append((parts[0], float(parts[-1].replace(",", "").replace(" ", ""))))
        except ValueError:
            continue  # header row or a bad number
    return rows


def main():
    if doc is None:
        return {"status": "no_active_document",
                "message": "Open a model in Revit, then run the report again."}
    if doc.IsFamilyDocument:
        return {"status": "family_document", "message": "The active document is a family."}

    if inputs.get("occupancy_snapshot") is True:
        return occupancy_snapshot()

    group_by = inputs.get("group_by") or "Department"
    conv, unit_label, units_ok = display_units()
    opts = DB.SpatialElementBoundaryOptions()
    rooms = room_elements()
    header = ["Element Id", "Number", "Name", "Level", group_by, "Phase", "Status",
              "Area (%s)" % unit_label, "Area (m2)", "Area (ft2)"]
    rows = []
    by_level, by_group, by_level_group = {}, {}, {}
    status_counts = {}
    group_missing = 0
    total_ft2 = 0.0
    for room in rooms:
        status = room_status(room, opts)
        status_counts[status] = status_counts.get(status, 0) + 1
        name_p = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
        name = name_p.AsString() if name_p else ""
        level = room.Level.Name if room.Level else "(no level)"
        grp = param_text(room, group_by)
        if grp is None:
            group_missing += 1
            grp = ""
        grp_key = grp or "(blank)"
        phase_p = room.get_Parameter(DB.BuiltInParameter.ROOM_PHASE)
        phase = phase_p.AsValueString() if phase_p else ""
        ft2 = room.Area if status == "placed" else 0.0
        rows.append([eid_int(room.Id), room.Number or "", name or "", level, grp, phase or "",
                     status, round(conv(ft2), 2), round(ft2 * FT2_TO_M2, 2), round(ft2, 2)])
        if status == "placed":
            total_ft2 += ft2
            add(by_level, level, ft2, conv)
            add(by_group, grp_key, ft2, conv)
            add(by_level_group, level + " | " + grp_key, ft2, conv)
    rows.sort(key=lambda r: (r[3], r[1], r[0]))

    notes = []
    if group_missing:
        notes.append("%d room(s) have no parameter named '%s'." % (group_missing, group_by))
    if not units_ok:
        notes.append("Project display units were not readable; display column is m2.")

    area_plans = None
    if inputs.get("include_area_plans", True):
        buckets = {}
        for a in (DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Areas)
                  .WhereElementIsNotElementType()):
            if a.Area <= 0:
                continue
            scheme = a.AreaScheme
            key = (scheme.Name if scheme else "(no scheme)",
                   bool(scheme.IsGrossBuildingArea) if scheme else False,
                   a.Level.Name if a.Level else "(no level)")
            b = buckets.setdefault(key, {"count": 0, "ft2": 0.0})
            b["count"] += 1
            b["ft2"] += a.Area
        area_plans = []
        for key in sorted(buckets.keys()):
            b = buckets[key]
            area_plans.append({"scheme": key[0], "is_gross_building": key[1], "level": key[2],
                               "count": b["count"], "area_display": round(conv(b["ft2"]), 2),
                               "area_m2": round(b["ft2"] * FT2_TO_M2, 2),
                               "area_ft2": round(b["ft2"], 2)})
        if not area_plans:
            notes.append("No placed Area elements. A gross (GIA-style) total needs an area plan; "
                         "the room total is a net (NIA-style) figure.")

    program = None
    if inputs.get("program_csv"):
        key_mode = inputs.get("program_key") or "group"
        t_units = inputs.get("program_units") or "display"
        tol = float(inputs.get("tolerance_pct") or 5)
        actual = {}
        for r in rows:
            if r[6] != "placed":
                continue
            k = (r[4] or "(blank)") if key_mode == "group" else (r[2] or "(blank)")
            actual[k.lower()] = actual.get(k.lower(), 0.0) + r[9]
        to_units = {"m2": lambda f: f * FT2_TO_M2, "ft2": lambda f: f}.get(t_units, conv)
        program = []
        seen = set()
        for key, target in parse_program(inputs.get("program_csv")):
            seen.add(key.lower())
            got = to_units(actual.get(key.lower(), 0.0))
            delta = got - target
            pct = (delta / target * 100.0) if target else None
            if key.lower() not in actual:
                state = "MISSING"
            elif pct is not None and abs(pct) <= tol:
                state = "OK"
            else:
                state = "OVER" if delta > 0 else "UNDER"
            program.append({"key": key, "target": round(target, 2), "actual": round(got, 2),
                            "delta": round(delta, 2),
                            "delta_pct": round(pct, 1) if pct is not None else None,
                            "status": state})
        extra = sorted(k for k in actual.keys() if k not in seen)
        if extra:
            notes.append("Model %s values not in the program: %s"
                         % (key_mode, ", ".join(extra[:30])))
        notes.append("Program targets read as %s." % (unit_label if t_units == "display" else t_units))

    return {
        "status": "ok", "document": doc.Title, "group_by": group_by,
        "units": {"display_label": unit_label, "display_readable": units_ok},
        "room_count": len(rows), "status_counts": status_counts,
        "total": {"area_display": round(conv(total_ft2), 2),
                  "area_m2": round(total_ft2 * FT2_TO_M2, 2), "area_ft2": round(total_ft2, 2)},
        "by_level": finish(by_level, conv), "by_group": finish(by_group, conv),
        "by_level_group": finish(by_level_group, conv),
        "area_plans": area_plans, "program": program,
        "header": header, "rows": rows, "notes": notes,
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


result = main()
if inputs.get("occupancy_snapshot") is not True:
    result = ascii_safe(result)
print("am-area-report: %s, %s rooms" % (result.get("status"), result.get("room_count")))

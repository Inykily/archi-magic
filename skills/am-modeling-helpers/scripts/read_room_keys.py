# -*- coding: utf-8 -*-
"""am-modeling-helpers: find room parameters that a key schedule drives (read only).

Submit the full text with run_query. IronPython 2.7 and CPython 3 (no
f-strings). The script opens no transaction and changes nothing.

Inputs:
  room_ids     1 to 500 target room ids (required)
  parameters   optional list of room parameter names (at most 10). The
               default is the four built-in room finish parameters
               (floor, base, wall, ceiling finish), by built-in id.

Result: {"payload": "<JSON text>"} with kind "room-key-read":
  key_schedules: [{id, name, key_parameter, fields, key_names, key_rows_read}]
  parameters:    the parameter names checked
  targets:       [{id, number, name, keys: {<key parameter>: {key_id, key_name}},
                   values: {<parameter>: {found, value, read_only}}}]
  key_usage:     {<key parameter>: {<key id>: {count, room_ids (first 500), truncated}}}
  key_rows:      {<key id>: {name, values: {<parameter>: value}}}
  scanned_rooms, scan_complete
A parameter that is read-only on a room that has a key, and that is a
field of that key schedule, is driven by the key. Decode the payload and
pass the file to room_key_plan.py.
"""
import json
import time

from pyrevit.api import DB

try:
    INPUTS = inputs  # noqa: F821  (injected by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}

MAX_TARGETS = 500
MAX_SCAN = 20000
MAX_LISTED = 500
TIME_BUDGET_S = 120.0
DEFAULT_BIPS = ["ROOM_FINISH_FLOOR", "ROOM_FINISH_BASE", "ROOM_FINISH_WALL", "ROOM_FINISH_CEILING"]


def eid(element_id):
    """ElementId -> int. Revit 2024+ has .Value; older years only .IntegerValue."""
    if hasattr(element_id, "Value"):
        return int(element_id.Value)
    return int(element_id.IntegerValue)


def make_id(value):
    try:
        from System import Int64
        return DB.ElementId(Int64(value))
    except Exception:
        return DB.ElementId(int(value))


def positive_ids(values, limit, label):
    if not isinstance(values, list) or not 1 <= len(values) <= limit:
        raise ValueError("Pass 1 to %d ids in inputs.%s." % (limit, label))
    ids = []
    for raw in values:
        text = str(raw).strip()
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("Ids must be positive whole numbers.")
        if int(text) not in ids:
            ids.append(int(text))
    return ids


def value_of(p):
    try:
        if p.StorageType == DB.StorageType.String:
            return p.AsString()
        return p.AsValueString()
    except Exception:
        return None


def key_name_of(element):
    if element is None:
        return None
    try:
        p = element.get_Parameter(DB.BuiltInParameter.REF_TABLE_ELEM_NAME)
        if p is not None and p.AsString():
            return p.AsString()
    except Exception:
        pass
    try:
        return element.Name
    except Exception:
        return None


def room_key_schedules(document):
    rooms_category = eid(DB.ElementId(DB.BuiltInCategory.OST_Rooms))
    rows = []
    for view in DB.FilteredElementCollector(document).OfClass(DB.ViewSchedule):
        try:
            if view.IsTemplate:
                continue
            definition = view.Definition
            if not definition.IsKeySchedule or eid(definition.CategoryId) != rooms_category:
                continue
            key_parameter = view.KeyScheduleParameterName
            fields = []
            for i in range(definition.GetFieldCount()):
                name = definition.GetField(i).GetName()
                if name and name != key_parameter:
                    fields.append(name)
        except Exception:
            continue
        key_names, rows_read = [], True
        try:
            for element in DB.FilteredElementCollector(document, view.Id).WhereElementIsNotElementType():
                name = key_name_of(element)
                if name:
                    key_names.append(name)
        except Exception:
            rows_read = False
        rows.append({"id": eid(view.Id), "name": view.Name, "key_parameter": key_parameter,
                     "fields": fields, "key_names": sorted(set(key_names)), "key_rows_read": rows_read})
    return rows


def parameter_specs(sample_room):
    """Return [(name, getter)] for the parameters to check."""
    names = INPUTS.get("parameters")
    specs = []
    if names:
        if not isinstance(names, list) or len(names) > 10:
            raise ValueError("Pass at most 10 names in inputs.parameters.")
        for name in names:
            specs.append((str(name), (lambda element, n=str(name): element.LookupParameter(n))))
        return specs
    for bip_name in DEFAULT_BIPS:
        bip = getattr(DB.BuiltInParameter, bip_name)
        name = bip_name
        try:
            p = sample_room.get_Parameter(bip) if sample_room is not None else None
            if p is not None:
                name = p.Definition.Name
        except Exception:
            pass
        specs.append((name, (lambda element, b=bip: element.get_Parameter(b))))
    return specs


def read_keys(document):
    target_ids = positive_ids(INPUTS.get("room_ids"), MAX_TARGETS, "room_ids")
    schedules = room_key_schedules(document)
    key_params = [s["key_parameter"] for s in schedules if s.get("key_parameter")]
    rooms = [(i, document.GetElement(make_id(i))) for i in target_ids]
    sample = None
    for _, room in rooms:
        if isinstance(room, DB.Architecture.Room):
            sample = room
            break
    specs = parameter_specs(sample)
    targets = []
    referenced = set()
    for room_id, room in rooms:
        if not isinstance(room, DB.Architecture.Room):
            targets.append({"id": room_id, "status": "room_not_found", "keys": {}, "values": {}})
            continue
        row = {"id": room_id,
               "number": value_of(room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)),
               "name": value_of(room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)),
               "status": "read", "keys": {}, "values": {}}
        for key_parameter in key_params:
            p = room.LookupParameter(key_parameter)
            if p is None or p.StorageType != DB.StorageType.ElementId:
                continue
            key_id = eid(p.AsElementId())
            if key_id > 0:
                referenced.add(key_id)
                row["keys"][key_parameter] = {"key_id": key_id,
                                              "key_name": key_name_of(document.GetElement(p.AsElementId()))}
            else:
                row["keys"][key_parameter] = {"key_id": None, "key_name": None}
        for name, getter in specs:
            try:
                p = getter(room)
            except Exception:
                p = None
            if p is None:
                row["values"][name] = {"found": False}
            else:
                row["values"][name] = {"found": True, "value": value_of(p), "read_only": bool(p.IsReadOnly)}
        targets.append(row)

    usage = dict((k, {}) for k in key_params)
    started = time.time()
    scanned = 0
    complete = True
    collector = (DB.FilteredElementCollector(document)
                 .OfCategory(DB.BuiltInCategory.OST_Rooms)
                 .WhereElementIsNotElementType())
    for room in collector:
        if scanned >= MAX_SCAN or time.time() - started > TIME_BUDGET_S:
            complete = False
            break
        scanned += 1
        for key_parameter in key_params:
            p = room.LookupParameter(key_parameter)
            if p is None or p.StorageType != DB.StorageType.ElementId:
                continue
            key_id = eid(p.AsElementId())
            if key_id <= 0:
                continue
            entry = usage[key_parameter].setdefault(str(key_id), {"count": 0, "room_ids": [], "truncated": False})
            entry["count"] += 1
            if len(entry["room_ids"]) < MAX_LISTED:
                entry["room_ids"].append(eid(room.Id))
            else:
                entry["truncated"] = True

    key_rows = {}
    for key_id in sorted(referenced):
        element = document.GetElement(make_id(key_id))
        values = {}
        for name, _ in specs:
            try:
                p = element.LookupParameter(name) if element is not None else None
            except Exception:
                p = None
            values[name] = value_of(p) if p is not None else None
        key_rows[str(key_id)] = {"name": key_name_of(element), "values": values}

    return {"kind": "room-key-read", "key_schedules": schedules,
            "parameters": [name for name, _ in specs], "targets": targets,
            "key_usage": usage, "key_rows": key_rows,
            "scanned_rooms": scanned, "scan_complete": complete}


if doc is None or doc.IsFamilyDocument:  # noqa: F821
    result = {"error": "no_project_document", "message": "Open a Revit project, not a family."}
else:
    try:
        result = {"payload": json.dumps(read_keys(doc), ensure_ascii=True)}  # noqa: F821
    except ValueError as exc:
        result = {"error": "bad_inputs", "message": str(exc)}

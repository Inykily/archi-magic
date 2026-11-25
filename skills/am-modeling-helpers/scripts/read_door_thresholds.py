# -*- coding: utf-8 -*-
"""Read doors, the floor finish on both sides, and the transition details. Read only.

Issue #299. Run with run_query. Changes nothing.

inputs: {"sill_parameter": "<door parameter name>",          (required)
         "finish_parameter": "<room parameter name>",        (default "Floor Finish")
         "sheet_ids": [<transition detail sheet ids>],       (required, max 50)
         "phase_id": <phase id>,                             (default: the last phase)
         "door_ids": [<door ids>]}                           (optional, default all doors)

Returns {"payload": "<JSON text>"} with
{"kind": "door-threshold-read", "document", "phase": {"id", "name"},
 "sill_parameter", "finish_parameter",
 "doors": [{"id", "mark", "level", "sill", "sill_found", "sill_read_only",
            "from_room": {"id", "number", "name", "finish"} or null,
            "to_room": {...} or null}],
 "details": [{"sheet_id", "sheet_number", "view_id", "view_name", "detail_number"}],
 "missing": [ids not found], "complete": bool}
From Room and To Room are read in the chosen phase.
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import json

from pyrevit.api import DB

MAX_DOORS = 5000
MAX_SHEETS = 50


def id_int(element_id):
    try:
        return int(element_id.Value)        # Revit 2024+
    except AttributeError:
        return int(element_id.IntegerValue)  # removed in Revit 2026


try:
    import System

    def eid(n):
        return DB.ElementId(System.Int64(int(n)))
except ImportError:
    def eid(n):
        return DB.ElementId(int(n))


def text_of(param):
    if param is None:
        return None
    try:
        if param.StorageType == DB.StorageType.String:
            return param.AsString()
    except Exception:
        pass
    return param.AsValueString()


def room_row(room, finish_parameter):
    if room is None:
        return None
    number = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
    name = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
    return {"id": id_int(room.Id), "number": text_of(number), "name": text_of(name),
            "finish": text_of(room.LookupParameter(finish_parameter))}


def pick_phase(phase_id):
    phases = list(doc.Phases)  # noqa: F821
    if phase_id is not None:
        for phase in phases:
            if id_int(phase.Id) == int(phase_id):
                return phase
        return None
    return phases[-1] if phases else None


def main():
    if doc is None or doc.IsFamilyDocument:  # noqa: F821
        return {"error": "no_project_document", "message": "Open a project model."}
    sill_name = inputs.get("sill_parameter")  # noqa: F821
    finish_name = inputs.get("finish_parameter") or "Floor Finish"  # noqa: F821
    sheet_ids = inputs.get("sheet_ids") or []  # noqa: F821
    if not sill_name or not sheet_ids:
        return {"error": "bad_inputs", "message": "inputs needs sill_parameter and sheet_ids."}
    if len(sheet_ids) > MAX_SHEETS:
        return {"error": "bad_inputs", "message": "Read at most %d sheets at a time." % MAX_SHEETS}
    phase = pick_phase(inputs.get("phase_id"))  # noqa: F821
    if phase is None:
        return {"error": "bad_inputs", "message": "The phase was not found."}
    missing, details = [], []
    for sid in sheet_ids:
        sheet = doc.GetElement(eid(sid))  # noqa: F821
        if not isinstance(sheet, DB.ViewSheet):
            missing.append(int(sid))
            continue
        for vp_id in sheet.GetAllViewports():
            vp = doc.GetElement(vp_id)  # noqa: F821
            view = doc.GetElement(vp.ViewId)  # noqa: F821
            number = vp.get_Parameter(DB.BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
            details.append({"sheet_id": id_int(sheet.Id), "sheet_number": sheet.SheetNumber,
                            "view_id": id_int(vp.ViewId), "view_name": view.Name if view else None,
                            "detail_number": text_of(number)})
    door_ids = inputs.get("door_ids")  # noqa: F821
    if door_ids:
        doors = []
        for i in door_ids:
            el = doc.GetElement(eid(i))  # noqa: F821
            if el is None:
                missing.append(int(i))
            else:
                doors.append(el)
    else:
        doors = list(DB.FilteredElementCollector(doc).OfCategory(  # noqa: F821
            DB.BuiltInCategory.OST_Doors).WhereElementIsNotElementType())
    complete = len(doors) <= MAX_DOORS
    rows = []
    for door in doors[:MAX_DOORS]:
        sill = door.LookupParameter(sill_name)
        mark = door.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
        level = doc.GetElement(door.LevelId) if door.LevelId is not None else None  # noqa: F821
        rows.append({"id": id_int(door.Id), "mark": text_of(mark),
                     "level": level.Name if level is not None else None,
                     "sill": text_of(sill), "sill_found": sill is not None,
                     "sill_read_only": bool(sill.IsReadOnly) if sill is not None else False,
                     "from_room": room_row(door.get_FromRoom(phase), finish_name),
                     "to_room": room_row(door.get_ToRoom(phase), finish_name)})
    return {"kind": "door-threshold-read", "document": doc.Title,  # noqa: F821
            "phase": {"id": id_int(phase.Id), "name": phase.Name},
            "sill_parameter": sill_name, "finish_parameter": finish_name,
            "doors": rows, "details": details, "missing": missing, "complete": complete}


report = main()
result = {"payload": json.dumps(report, ensure_ascii=True)}

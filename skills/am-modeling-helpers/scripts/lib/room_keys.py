# -*- coding: utf-8 -*-
"""Find room parameters that a room key schedule drives, and plan the change.

Pure Python (CPython 3 and IronPython 2.7). Input is the report of
read_room_keys.py.

A field case (issue #132): setting a room's Floor Finish failed with
"The parameter is read-only." A room key schedule drove the finish
parameters, and many unrelated rooms shared the key. The fix was a new key
for the target rooms. This module finds that case before any write:

- writable: the room parameter is not read-only. Set it on the room.
- key_driven: the parameter is read-only, a key is set on the room, and
  that key schedule has a field with the parameter name.
- read_only_other: read-only for another reason (for example a formula or
  a group). This module cannot fix it.
- missing: the room has no parameter with that name.

For each key that drives a target room it recommends:

- edit_key when no other room uses the key (only the target rooms change),
- new_key when other rooms use the key (copy the key row, change the
  value, assign the new key to the target rooms only).
"""
from __future__ import division

from payload import change_preview

WRITABLE = "writable"
KEY_DRIVEN = "key_driven"
READ_ONLY_OTHER = "read_only_other"
MISSING = "missing"

EDIT_KEY = "edit-key"
NEW_KEY = "new-key"
SET_ROOMS = "set-rooms"


def _schedules_by_parameter(read):
    out = {}
    for schedule in read.get("key_schedules", []):
        name = schedule.get("key_parameter")
        if name:
            out[name] = schedule
    return out


def _key_name(read, key_id):
    row = (read.get("key_rows") or {}).get(str(key_id)) or {}
    return row.get("name")


def room_state(room, parameter, schedules):
    """Classify one target room for one parameter."""
    value = (room.get("values") or {}).get(parameter)
    state = {"room_id": room.get("id"), "number": room.get("number"), "name": room.get("name")}
    if not value or not value.get("found"):
        state["state"] = MISSING
        return state
    state["value"] = value.get("value")
    if not value.get("read_only"):
        state["state"] = WRITABLE
        return state
    for key_parameter, key in sorted((room.get("keys") or {}).items()):
        schedule = schedules.get(key_parameter)
        if not key or key.get("key_id") is None or schedule is None:
            continue
        if parameter in (schedule.get("fields") or []):
            state.update({
                "state": KEY_DRIVEN,
                "key_parameter": key_parameter,
                "key_id": key["key_id"],
                "key_name": key.get("key_name"),
                "schedule_id": schedule.get("id"),
                "schedule_name": schedule.get("name"),
            })
            return state
    state["state"] = READ_ONLY_OTHER
    return state


def analyze(read, parameter):
    """Classify every target room and group the key-driven rooms by key."""
    schedules = _schedules_by_parameter(read)
    rooms = [room_state(room, parameter, schedules) for room in read.get("targets", [])]
    target_ids = set(r["room_id"] for r in rooms)
    complete = bool(read.get("scan_complete", False))
    groups = {}
    for r in rooms:
        if r["state"] != KEY_DRIVEN:
            continue
        key = (r["key_parameter"], r["key_id"])
        group = groups.get(key)
        if group is None:
            usage = ((read.get("key_usage") or {}).get(r["key_parameter"]) or {}).get(str(r["key_id"])) or {}
            using_ids = [int(i) for i in usage.get("room_ids", [])]
            total = int(usage.get("count", len(using_ids)))
            key_row = (read.get("key_rows") or {}).get(str(r["key_id"])) or {}
            group = groups[key] = {
                "key_parameter": r["key_parameter"],
                "key_id": r["key_id"],
                "key_name": r.get("key_name") or key_row.get("name"),
                "schedule_id": r.get("schedule_id"),
                "schedule_name": r.get("schedule_name"),
                "key_value": (key_row.get("values") or {}).get(parameter),
                "rooms_using": total,
                "listed_ids": using_ids,
                "ids_truncated": bool(usage.get("truncated")) or len(using_ids) < total,
                "target_room_ids": [],
            }
        group["target_room_ids"].append(r["room_id"])
    result_groups = []
    for key in sorted(groups):
        group = groups[key]
        others = [i for i in group.pop("listed_ids") if i not in target_ids]
        other_count = group["rooms_using"] - len(group["target_room_ids"])
        group["other_room_count"] = max(other_count, len(others))
        group["other_room_ids"] = others[:50]
        if not complete:
            group["recommended"] = NEW_KEY
            group["reason"] = "The room scan is incomplete. Other rooms may use this key."
        elif group["other_room_count"] == 0:
            group["recommended"] = EDIT_KEY
            group["reason"] = "Only the listed rooms use this key."
        else:
            group["recommended"] = NEW_KEY
            group["reason"] = "%d other rooms use this key. Editing it changes them too." % group["other_room_count"]
        result_groups.append(group)
    counts = {}
    for r in rooms:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    warnings = []
    if not complete:
        warnings.append("The key usage scan stopped early. Do not edit a shared key from this read.")
    return {"kind": "room-key-analysis", "parameter": parameter, "scan_complete": complete,
            "counts": counts, "rooms": rooms, "groups": result_groups, "warnings": warnings}


def _existing_key_names(read, schedule_id):
    for schedule in read.get("key_schedules", []):
        if schedule.get("id") == schedule_id:
            return set(n for n in (schedule.get("key_names") or []) if n)
    return set()


def build_preview(read, analysis, option, new_value, key_id=None, new_key_name=None):
    """Change preview (am-safe-change format) for one decision.

    option set-rooms: set the value on the writable target rooms.
    option edit-key: change the value on one key row (key_id).
    option new-key: add a key row copied from key_id, set the value, and
    assign it to the target rooms that use key_id.
    """
    parameter = analysis["parameter"]
    columns = ["ElementId", "Kind", "Room", "Key", parameter]
    before, after, warnings, notes, steps = [], [], [], [], []
    if option == SET_ROOMS:
        rooms = [r for r in analysis["rooms"] if r["state"] == WRITABLE]
        for r in rooms:
            before.append([r["room_id"], "Room", r.get("number"), "", r.get("value")])
            after.append([r["room_id"], "Room", r.get("number"), "", new_value])
        steps.append({"op": "set_room_parameter", "parameter": parameter, "value": new_value,
                      "room_ids": [r["room_id"] for r in rooms]})
        skipped = [r for r in analysis["rooms"] if r["state"] != WRITABLE]
        if skipped:
            notes.append("%d listed rooms are not writable and are not in this change." % len(skipped))
        title = "Set %s on %d rooms" % (parameter, len(rooms))
        ownership = [r["room_id"] for r in rooms]
        changed = [parameter]
    else:
        group = None
        for g in analysis["groups"]:
            if str(g["key_id"]) == str(key_id):
                group = g
        if group is None:
            raise ValueError("No listed room uses key %s." % key_id)
        target_rooms = [r for r in analysis["rooms"] if r.get("key_id") == group["key_id"]]
        old_value = group.get("key_value")
        if option == EDIT_KEY:
            before.append([group["key_id"], "Key row", "", group["key_name"], old_value])
            after.append([group["key_id"], "Key row", "", group["key_name"], new_value])
            for r in target_rooms:
                before.append([r["room_id"], "Room (by key)", r.get("number"), group["key_name"], r.get("value")])
                after.append([r["room_id"], "Room (by key)", r.get("number"), group["key_name"], new_value])
            if group["other_room_count"]:
                warnings.append({"row": str(group["key_id"]), "blocking": False,
                                 "text": "This also changes %d rooms that are not in your list." % group["other_room_count"]})
                notes.append("Other rooms that use this key (first 50): %s" % ", ".join(
                    str(i) for i in group["other_room_ids"]))
            if not analysis.get("scan_complete"):
                warnings.append({"row": str(group["key_id"]), "blocking": True,
                                 "text": "The key usage scan is incomplete. Read again before you edit a key row."})
            steps.append({"op": "set_key_parameter", "key_id": group["key_id"],
                          "parameter": parameter, "value": new_value})
            title = "Change %s on key %s" % (parameter, group["key_name"])
            ownership = [group["key_id"]]
            changed = [parameter]
        elif option == NEW_KEY:
            name = (new_key_name or "").strip()
            if not name:
                warnings.append({"row": "new", "blocking": True, "text": "Give a name for the new key."})
            elif name in _existing_key_names(read, group.get("schedule_id")) or name == group["key_name"]:
                warnings.append({"row": "new", "blocking": True,
                                 "text": "A key named '%s' already exists. Pick another name." % name})
            before.append(["new", "New key row", "", "", ""])
            after.append(["new", "New key row", "", name, new_value])
            for r in target_rooms:
                before.append([r["room_id"], "Room", r.get("number"), group["key_name"], r.get("value")])
                after.append([r["room_id"], "Room", r.get("number"), name, new_value])
            notes.append("The new key copies every other value from key '%s'." % group["key_name"])
            steps.append({"op": "add_key_row", "schedule_id": group.get("schedule_id"),
                          "copy_from_key_id": group["key_id"], "key_name": name,
                          "set": {parameter: new_value}})
            steps.append({"op": "assign_key", "key_parameter": group["key_parameter"],
                          "key_name": name, "room_ids": [r["room_id"] for r in target_rooms]})
            title = "New key %s for %d rooms" % (name, len(target_rooms))
            # The new row changes the key schedule, so its owner must not be another user.
            ownership = ([group["schedule_id"]] if group.get("schedule_id") else []) + \
                [r["room_id"] for r in target_rooms]
            changed = ["Key", parameter]
        else:
            raise ValueError("Unknown option %r." % option)
    return change_preview(title, columns, changed, before, after, notes=notes, warnings=warnings,
                          steps=steps, ownership_ids=ownership, params={"option": option})

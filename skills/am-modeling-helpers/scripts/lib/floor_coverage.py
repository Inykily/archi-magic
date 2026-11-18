# -*- coding: utf-8 -*-
"""Which floors lie in which rooms, and what to do with each finish floor.

Pure Python (CPython 3 and IronPython 2.7). Input is the report of
read_floor_room_coverage.py. That read intersects each floor solid with
the room outline extruded up and down, and reads the upward face area of
the result (the method that worked in the field for issue #132).

User rules from the field (issue #132), enforced here:

1. Never change the structural slab. A floor with the Structural flag is
   "protected". It is never in a plan step, and a decision for it is a
   blocking warning. When the user names the finish floor types, every
   other type is protected too.
2. Split the existing finish floor. Do not draw a second floor over it.
3. Ask before each action. The plan has one question per floor.
4. Show how much of each floor is in scope before the commit (share).
"""
from __future__ import division

from payload import change_preview

DEFAULT_RULES = {
    "min_overlap_sf": 0.5,   # smaller overlaps are noise (edges, under walls)
    "min_share": 0.02,       # below this share the floor only touches the rooms
    "full_share": 0.98,      # at or above this share the floor is inside the rooms
    "room_gap": 0.95,        # finish floor coverage of a room below this is a gap
    "room_double": 1.05,     # coverage above this means floors overlap in plan
    "piece_min_sf": 2.0,     # a split piece below this is a sliver
    "offset_tolerance_ft": 1e-4,
}

PROTECTED = "protected"
FINISH = "finish"

NEVER_CHANGE = "never_change"
NO_TARGET = "no_target"
EDGE_ONLY = "edge_only"
RETYPE_WHOLE = "retype_whole"
RETYPE_OR_SPLIT = "retype_whole_or_split"
SPLIT_OR_ASK = "split_or_ask"
UNRESOLVED = "unresolved"

RETYPE = "retype"
SPLIT = "split"
SKIP = "skip"


def _rules(rules):
    r = dict(DEFAULT_RULES)
    r.update(rules or {})
    return r


def summarize(read, finish_type_ids=None, rules=None):
    """Per floor: rooms, share in scope, role and proposed action. Per room: coverage."""
    r = _rules(rules)
    finish_types = set(int(i) for i in (finish_type_ids or []))
    rooms = dict((room["id"], room) for room in read.get("rooms", []))
    pairs_by_floor = {}
    failed_by_floor = {}
    for pair in read.get("pairs", []):
        if pair.get("status") != "ok":
            failed_by_floor.setdefault(pair["floor_id"], []).append(pair)
            continue
        if pair.get("overlap_sf", 0.0) >= r["min_overlap_sf"]:
            pairs_by_floor.setdefault(pair["floor_id"], []).append(pair)

    floors = []
    for floor in read.get("floors", []):
        fid = floor["id"]
        top = float(floor.get("top_area_sf") or 0.0)
        in_rooms = []
        for pair in sorted(pairs_by_floor.get(fid, []), key=lambda p: -p["overlap_sf"]):
            room = rooms.get(pair["room_id"], {})
            in_rooms.append({"room_id": pair["room_id"], "number": room.get("number"),
                             "name": room.get("name"), "area_sf": round(pair["overlap_sf"], 3),
                             "share_of_floor": (pair["overlap_sf"] / top) if top > 0 else None,
                             "share_of_room": (pair["overlap_sf"] / room["area_sf"])
                             if room.get("area_sf") else None})
        in_scope = sum(p["area_sf"] for p in in_rooms)
        share = (in_scope / top) if top > 0 else None
        row = {
            "id": fid, "uid": floor.get("uid"), "type_id": floor.get("type_id"),
            "type_name": floor.get("type_name"), "level_name": floor.get("level_name"),
            "is_structural": bool(floor.get("is_structural")),
            "height_offset_ft": floor.get("height_offset_ft"),
            "thickness_ft": floor.get("thickness_ft"),
            "top_area_sf": round(top, 3), "in_scope_sf": round(in_scope, 3),
            "share_in_scope": share, "outside_sf": round(max(top - in_scope, 0.0), 3),
            "rooms": in_rooms, "warnings": [],
        }
        if row["is_structural"]:
            row["role"], row["protected_reason"] = PROTECTED, "structural"
        elif finish_types and floor.get("type_id") not in finish_types:
            row["role"], row["protected_reason"] = PROTECTED, "not a finish floor type"
        else:
            row["role"] = FINISH
        if fid in failed_by_floor:
            row["warnings"].append("Revit could not intersect this floor with %d room(s)." % len(failed_by_floor[fid]))
        if floor.get("in_group"):
            row["warnings"].append("The floor is in a group. Revit can refuse to edit it.")
        if floor.get("pinned"):
            row["warnings"].append("The floor is pinned.")
        if floor.get("sloped"):
            row["warnings"].append("The floor top is sloped or shape-edited.")

        if row["role"] == PROTECTED:
            row["action"] = NEVER_CHANGE
        elif fid in failed_by_floor:
            row["action"] = UNRESOLVED
        elif not in_rooms or share is None:
            row["action"] = NO_TARGET
        elif share < r["min_share"]:
            row["action"] = EDGE_ONLY
        elif share >= r["full_share"]:
            row["action"] = RETYPE_WHOLE if len(in_rooms) == 1 else RETYPE_OR_SPLIT
        else:
            row["action"] = SPLIT_OR_ASK
        floors.append(row)

    by_id = dict((f["id"], f) for f in floors)
    room_rows = []
    offset_warnings = []
    for room in read.get("rooms", []):
        row = {"id": room["id"], "number": room.get("number"), "name": room.get("name"),
               "area_sf": room.get("area_sf"), "status": room.get("status")}
        if room.get("status") != "read":
            row.update({"coverage": None, "verdict": "excluded", "reason": room.get("reason")})
            room_rows.append(row)
            continue
        finish, protected = [], []
        for pair in read.get("pairs", []):
            if pair["room_id"] != room["id"] or pair.get("status") != "ok":
                continue
            if pair.get("overlap_sf", 0.0) < r["min_overlap_sf"]:
                continue
            floor = by_id.get(pair["floor_id"])
            if floor is None:
                continue
            entry = {"floor_id": floor["id"], "type_name": floor["type_name"],
                     "area_sf": round(pair["overlap_sf"], 3),
                     "height_offset_ft": floor.get("height_offset_ft")}
            (finish if floor["role"] == FINISH else protected).append(entry)
        covered = sum(e["area_sf"] for e in finish)
        coverage = (covered / room["area_sf"]) if room.get("area_sf") else None
        if coverage is None:
            verdict = "excluded"
        elif coverage < r["room_gap"]:
            verdict = "gap"
        elif coverage > r["room_double"]:
            verdict = "double"
        else:
            verdict = "ok"
        row.update({"coverage": coverage, "verdict": verdict,
                    "finish_floors": finish, "protected_floors": protected})
        offsets = sorted(set(round(e["height_offset_ft"] or 0.0, 4) for e in finish))
        if len(offsets) > 1 and offsets[-1] - offsets[0] > r["offset_tolerance_ft"]:
            offset_warnings.append(
                "Room %s has finish floors at different height offsets (%s ft). A floor at another "
                "offset next to its neighbours can give 'Highlighted floors overlap' warnings."
                % (room.get("number") or room["id"], ", ".join("%.4f" % o for o in offsets)))
        room_rows.append(row)

    counts = {}
    for f in floors:
        counts[f["action"]] = counts.get(f["action"], 0) + 1
    notes = []
    if not finish_types:
        notes.append("No finish floor types were given. Every floor without the Structural flag "
                     "is treated as a finish floor. Ask the user to confirm the finish types.")
    if not read.get("complete", True):
        notes.append("The read is incomplete. Read the pending rooms before you plan: %s." % ", ".join(
            str(i) for i in read.get("pending_room_ids", [])))
    return {"kind": "floor-coverage-summary", "rules": r, "complete": bool(read.get("complete", True)),
            "finish_type_ids": sorted(finish_types), "counts": counts, "floors": floors,
            "rooms": room_rows, "warnings": offset_warnings, "notes": notes}


def _pct(value):
    return "?" if value is None else "%.0f%%" % (100.0 * value)


def questions(summary):
    """One question per finish floor that needs a decision (rule 3: ask before each action)."""
    out = []
    for floor in summary["floors"]:
        action = floor["action"]
        if action not in (RETYPE_WHOLE, RETYPE_OR_SPLIT, SPLIT_OR_ASK):
            continue
        rooms = ", ".join("%s (%s)" % (r.get("number") or r["room_id"], _pct(r["share_of_floor"]))
                          for r in floor["rooms"])
        text = "Floor %s (%s): %s of its area is in the listed rooms: %s." % (
            floor["id"], floor["type_name"], _pct(floor["share_in_scope"]), rooms)
        if action == RETYPE_WHOLE:
            options = [RETYPE, SKIP]
        elif action == RETYPE_OR_SPLIT:
            options = [RETYPE, SPLIT, SKIP]
        else:
            options = [SPLIT, RETYPE, SKIP]
            text += " A retype also changes %.1f sf outside the listed rooms." % floor["outside_sf"]
        out.append({"floor_id": floor["id"], "action": action, "text": text,
                    "options": options, "recommended": options[0]})
    return out


def build_preview(summary, decisions, new_type_id, new_type_name, rules=None):
    """Change preview for the decided floors. decisions: {floor_id: retype|split|skip}."""
    r = _rules(rules if rules is not None else summary.get("rules"))
    by_id = dict((f["id"], f) for f in summary["floors"])
    columns = ["Piece", "Floor", "Room", "Area sf", "Floor type"]
    before, after, warnings, notes, steps, ownership = [], [], [], [], [], []
    if not summary.get("complete", True):
        warnings.append({"row": "read", "blocking": True,
                         "text": "The coverage read is incomplete. Read the pending rooms first."})
    if new_type_id is None or not new_type_name:
        warnings.append({"row": "type", "blocking": True, "text": "Give the new finish floor type (id and name)."})
    for floor_id in sorted(decisions):
        decision = decisions[floor_id]
        floor = by_id.get(floor_id)
        if floor is None:
            warnings.append({"row": str(floor_id), "blocking": True,
                             "text": "Floor %s is not in the coverage read." % floor_id})
            continue
        if decision == SKIP:
            notes.append("Floor %s: skipped by the user." % floor_id)
            continue
        if floor["role"] == PROTECTED:
            warnings.append({"row": str(floor_id), "blocking": True,
                             "text": "Floor %s is protected (%s). This plan never changes it."
                             % (floor_id, floor.get("protected_reason"))})
            continue
        if floor["action"] in (UNRESOLVED, NO_TARGET, EDGE_ONLY):
            warnings.append({"row": str(floor_id), "blocking": True,
                             "text": "Floor %s has action '%s'. It is not a retype or split candidate."
                             % (floor_id, floor["action"])})
            continue
        old = floor["type_name"]
        ownership.append(floor_id)
        for text in floor["warnings"]:
            warnings.append({"row": str(floor_id), "blocking": False, "text": text})
        if decision == RETYPE:
            before.append([str(floor_id), floor_id, "(whole floor)", floor["top_area_sf"], old])
            after.append([str(floor_id), floor_id, "(whole floor)", floor["top_area_sf"], new_type_name])
            if floor["outside_sf"] >= r["min_overlap_sf"]:
                warnings.append({"row": str(floor_id), "blocking": False,
                                 "text": "The retype also changes %.1f sf (%s) outside the listed rooms."
                                 % (floor["outside_sf"], _pct(1.0 - (floor["share_in_scope"] or 0.0)))})
            steps.append({"op": "retype_floor", "floor_id": floor_id, "floor_uid": floor["uid"],
                          "from_type_id": floor["type_id"], "to_type_id": new_type_id})
        elif decision == SPLIT:
            for piece in floor["rooms"]:
                key = "%s:%s" % (floor_id, piece["room_id"])
                label = piece.get("number") or piece["room_id"]
                before.append([key, floor_id, label, piece["area_sf"], old])
                after.append([key, floor_id, label, piece["area_sf"], new_type_name])
                if piece["area_sf"] < r["piece_min_sf"]:
                    warnings.append({"row": key, "blocking": False,
                                     "text": "Piece in room %s is only %.2f sf (a sliver)." % (label, piece["area_sf"])})
            rest = floor["outside_sf"]
            key = "%s:rest" % floor_id
            before.append([key, floor_id, "(outside the listed rooms)", rest, old])
            after.append([key, floor_id, "(outside the listed rooms)", rest, old])
            if rest < r["min_overlap_sf"]:
                warnings.append({"row": key, "blocking": False,
                                 "text": "Nothing of floor %s stays outside the rooms. A retype is simpler." % floor_id})
            elif rest < r["piece_min_sf"]:
                warnings.append({"row": key, "blocking": False,
                                 "text": "The rest of floor %s is a %.2f sf sliver (often strips under walls)."
                                 % (floor_id, rest)})
            steps.append({"op": "split_floor_by_rooms", "floor_id": floor_id, "floor_uid": floor["uid"],
                          "room_ids": [p["room_id"] for p in floor["rooms"]],
                          "piece_type_id": new_type_id, "rest_type_id": floor["type_id"],
                          "height_offset_ft": floor.get("height_offset_ft")})
        else:
            warnings.append({"row": str(floor_id), "blocking": True,
                             "text": "Unknown decision '%s' for floor %s." % (decision, floor_id)})
    protected = [f for f in summary["floors"] if f["role"] == PROTECTED and f["rooms"]]
    if protected:
        notes.append("Protected floors under these rooms, never changed: %s." % ", ".join(
            "%s (%s)" % (f["id"], f["type_name"]) for f in protected))
    notes.extend(summary.get("warnings", []))
    title = "Finish floors in %d room(s): %d floor(s)" % (len(summary["rooms"]), len(steps))
    return change_preview(title, columns, ["Floor type"], before, after, notes=notes, warnings=warnings,
                          steps=steps, ownership_ids=ownership,
                          params={"new_type_id": new_type_id, "new_type_name": new_type_name,
                                  "decisions": dict((str(k), v) for k, v in decisions.items())},
                          expected_dependent_categories=["Floors", "Rooms"])

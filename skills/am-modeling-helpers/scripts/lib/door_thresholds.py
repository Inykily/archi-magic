# -*- coding: utf-8 -*-
"""Match door sills to transition details from the floor finishes on both sides.

Issue #299 (first step). A door schedule had an empty SILL value for most
doors. The wanted value is the transition detail reference
"<detail number>/<sheet number>" of the detail that shows the joint
between the floor finish of the door's From Room and its To Room.

The field data showed why this needs care:
- Room floor finish values are free text. One room can hold several
  codes ("CPT/TZ", "CPT, RF"). Some values are "-" or empty.
- Rooms hold codes (CPT, TZ, RF). Detail view names hold words
  (Carpet, Terrazzo, Rubber). A code-to-word map is needed, and the user
  must confirm it.

This module plans; it changes nothing. Only clear matches become steps.
Every other door is listed with a status for the user.

Pure computation. Runs under CPython 3 and IronPython 2.7: no f-strings,
no type annotations, no nonlocal. No Revit imports.
"""
from __future__ import division, print_function

import re

import payload

READ_KIND = "door-threshold-read"

MATCH = "match"
NO_MATCH = "no_match"
AMBIGUOUS = "more_than_one_match"
MIXED = "mixed_finish"
EMPTY = "empty_finish"
UNKNOWN_CODE = "unknown_code"
SAME = "same_finish"
EXTERIOR = "one_side_no_room"
NO_ROOMS = "no_rooms"
HAS_VALUE = "has_value"
READ_ONLY = "read_only"
NO_PARAMETER = "no_parameter"

STATUSES = (MATCH, NO_MATCH, AMBIGUOUS, MIXED, EMPTY, UNKNOWN_CODE, SAME, EXTERIOR,
            NO_ROOMS, HAS_VALUE, READ_ONLY, NO_PARAMETER)

STATUS_TEXT = {
    MATCH: "One transition detail matches. The plan writes it.",
    NO_MATCH: "No transition detail shows this finish pair.",
    AMBIGUOUS: "More than one transition detail shows this finish pair.",
    MIXED: "A room holds more than one finish code.",
    EMPTY: "A room has no floor finish value.",
    UNKNOWN_CODE: "A finish code is not in the confirmed map.",
    SAME: "Both rooms have the same finish. A threshold detail is not certain.",
    EXTERIOR: "One side has no room (often an outside door).",
    NO_ROOMS: "Neither side has a room.",
    HAS_VALUE: "The sill parameter already has a value. The plan keeps it.",
    READ_ONLY: "The sill parameter is read-only on this door.",
    NO_PARAMETER: "The door has no parameter with the sill name.",
}

DEFAULT_SEPARATORS = "/,;+&"
EMPTY_VALUES = ("", "-", "--", "n/a", "na", "none")
DEFAULT_FORMAT = "{detail}/{sheet}"


class MapError(payload.InputError):
    """The finish map is not usable."""


# ------------------------------------------------------------ finishes

def split_finishes(value, separators=DEFAULT_SEPARATORS):
    """'CPT / tz' -> ['CPT', 'TZ']. Empty values and '-' give []."""
    if value is None:
        return []
    text = str(value)
    for sep in separators:
        text = text.replace(sep, "\n")
    out = []
    for part in text.split("\n"):
        code = part.strip().upper()
        if code.lower() in EMPTY_VALUES:
            continue
        if code not in out:
            out.append(code)
    return out


# ----------------------------------------------------------------- map

def load_map(data):
    """Check a finish map.

    {"confirmed": true,
     "codes": {"CPT": ["carpet"], "TZ": ["terrazzo", "tz"], "RF": "rubber"},
     "details": {"5/A-501": ["CPT", "TZ"]},     (optional manual pairs)
     "separators": "/,"}                         (optional)
    Word matching ignores case and needs whole words.
    """
    if not isinstance(data, dict) or not isinstance(data.get("codes"), dict) or not data["codes"]:
        raise MapError("The finish map needs a 'codes' object: code -> word or list of words.")
    codes = {}
    for code, words in data["codes"].items():
        if isinstance(words, payload.TEXT):
            words = [words]
        words = [str(w).strip().lower() for w in words or [] if str(w).strip()]
        if not words:
            raise MapError("Code %s has no word." % code)
        codes[str(code).strip().upper()] = words
    details = {}
    for ref, pair in (data.get("details") or {}).items():
        pair = [str(c).strip().upper() for c in pair or []]
        if len(pair) != 2:
            raise MapError("Manual pair for %s needs exactly 2 codes." % ref)
        details[str(ref)] = pair
    return {"confirmed": bool(data.get("confirmed")), "codes": codes, "details": details,
            "separators": data.get("separators") or DEFAULT_SEPARATORS}


def _word_pattern(word):
    return re.compile(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", re.IGNORECASE)


def codes_in_name(name, finish_map):
    """The codes whose words appear in a detail view name, in order of appearance."""
    hits = []
    text = name or ""
    for code, words in finish_map["codes"].items():
        first = None
        for word in words:
            m = _word_pattern(word).search(text)
            if m and (first is None or m.start() < first):
                first = m.start()
        if first is not None:
            hits.append((first, code))
    return [code for _pos, code in sorted(hits)]


def pair_key(a, b):
    """Order-free key of a finish pair: 'CPT|TZ' for (TZ, CPT) and (CPT, TZ)."""
    return "|".join(sorted([a, b]))


def detail_ref(detail, fmt=DEFAULT_FORMAT):
    return fmt.replace("{detail}", str(detail.get("detail_number") or "")).replace(
        "{sheet}", str(detail.get("sheet_number") or ""))


def parse_details(details, finish_map, fmt=DEFAULT_FORMAT):
    """Each detail with its finish pair, or the reason it has none.

    Returns (rows, index). rows: [{"ref", "view_name", "codes", "pair",
    "source"}]; pair is None when the name does not give exactly 2 codes.
    index: {pair_key: [ref, ...]}.
    """
    rows, index = [], {}
    for d in details:
        ref = detail_ref(d, fmt)
        manual = finish_map["details"].get(ref)
        if manual:
            codes, source = list(manual), "manual"
        else:
            codes, source = codes_in_name(d.get("view_name"), finish_map), "name"
        pair = pair_key(codes[0], codes[1]) if len(codes) == 2 else None
        rows.append({"ref": ref, "view_name": d.get("view_name"), "codes": codes,
                     "pair": pair, "source": source})
        if pair:
            refs = index.setdefault(pair, [])
            if ref not in refs:
                refs.append(ref)
    return rows, index


# --------------------------------------------------------------- doors

def _room_label(room):
    if not room:
        return ""
    return ("%s %s" % (room.get("number") or "", room.get("name") or "")).strip()


def classify_door(door, finish_map, index):
    """Status, finish codes on both sides, and the matched refs of one door."""
    rooms = [door.get("from_room"), door.get("to_room")]
    out = {"id": door.get("id"), "mark": door.get("mark"), "level": door.get("level"),
           "from_room": _room_label(rooms[0]), "to_room": _room_label(rooms[1]),
           "from_finish": (rooms[0] or {}).get("finish"), "to_finish": (rooms[1] or {}).get("finish"),
           "sill": door.get("sill"), "refs": [], "status": None}
    if not door.get("sill_found", True):
        out["status"] = NO_PARAMETER
        return out
    if door.get("sill") not in (None, ""):
        out["status"] = HAS_VALUE
        return out
    if door.get("sill_read_only"):
        out["status"] = READ_ONLY
        return out
    present = [r for r in rooms if r]
    if not present:
        out["status"] = NO_ROOMS
        return out
    if len(present) == 1:
        out["status"] = EXTERIOR
        return out
    sides = [split_finishes(r.get("finish"), finish_map["separators"]) for r in rooms]
    if not sides[0] or not sides[1]:
        out["status"] = EMPTY
        return out
    if len(sides[0]) > 1 or len(sides[1]) > 1:
        out["status"] = MIXED
        return out
    a, b = sides[0][0], sides[1][0]
    out["codes"] = [a, b]
    if a not in finish_map["codes"] or b not in finish_map["codes"]:
        out["status"] = UNKNOWN_CODE
        return out
    if a == b:
        out["status"] = SAME
        return out
    refs = index.get(pair_key(a, b)) or []
    out["refs"] = list(refs)
    if len(refs) == 1:
        out["status"] = MATCH
    elif refs:
        out["status"] = AMBIGUOUS
    else:
        out["status"] = NO_MATCH
    return out


def analyse(read, finish_map, fmt=DEFAULT_FORMAT):
    """The full report: details with pairs, room codes, and one row per door."""
    detail_rows, index = parse_details(read.get("details") or [], finish_map, fmt)
    doors = [classify_door(d, finish_map, index) for d in read.get("doors") or []]
    counts = {}
    for d in doors:
        counts[d["status"]] = counts.get(d["status"], 0) + 1
    room_codes = {}
    for d in read.get("doors") or []:
        for side in ("from_room", "to_room"):
            room = d.get(side)
            if room:
                for code in split_finishes(room.get("finish"), finish_map["separators"]):
                    room_codes[code] = room_codes.get(code, 0) + 1
    warnings = []
    if not finish_map["confirmed"]:
        warnings.append({"row": "", "blocking": True,
                         "text": "The code-to-word map is not confirmed. Show it to the user and set "
                                 "\"confirmed\": true before any write."})
    unknown = sorted(c for c in room_codes if c not in finish_map["codes"])
    if unknown:
        warnings.append({"row": "", "blocking": False,
                         "text": "Room finish codes not in the map: %s." % ", ".join(unknown)})
    unparsed = [r for r in detail_rows if not r["pair"]]
    if unparsed:
        warnings.append({"row": "", "blocking": False,
                         "text": "%d detail name(s) give no finish pair, for example '%s'. Add words to "
                                 "the map or a manual pair." % (len(unparsed), unparsed[0]["view_name"])})
    for key, refs in sorted(index.items()):
        if len(refs) > 1:
            warnings.append({"row": "", "blocking": False,
                             "text": "Finish pair %s has %d details: %s." % (key, len(refs), ", ".join(refs))})
    return {"kind": "door-threshold-plan", "sill_parameter": read.get("sill_parameter"),
            "finish_parameter": read.get("finish_parameter"), "phase": read.get("phase"),
            "format": fmt, "details": detail_rows, "pairs": index, "room_codes": room_codes,
            "doors": doors, "counts": counts, "warnings": warnings,
            "map_confirmed": finish_map["confirmed"]}


def build_preview(analysis):
    """Change preview for am-safe-change: clear matches only."""
    param = analysis.get("sill_parameter") or "Sill"
    before, after, steps, ids = [], [], [], []
    for d in analysis["doors"]:
        if d["status"] != MATCH:
            continue
        before.append([d["id"], d.get("mark"), d.get("sill") or ""])
        after.append([d["id"], d.get("mark"), d["refs"][0]])
        steps.append({"op": "set_parameter", "element_id": d["id"], "parameter": param,
                      "value": d["refs"][0], "expect_before": d.get("sill") or "",
                      "finish_pair": d.get("codes")})
        ids.append(d["id"])
    warnings = list(analysis["warnings"])
    if not steps:
        warnings.append({"row": "", "blocking": True, "text": "No door has a clear match. Nothing to write."})
    total = len(analysis["doors"])
    notes = ["%d of %d doors get a sill value. %d are listed for the user and not changed."
             % (len(steps), total, total - len(steps))]
    for status in STATUSES:
        n = analysis["counts"].get(status)
        if n and status != MATCH:
            notes.append("%s: %d. %s" % (status, n, STATUS_TEXT[status]))
    preview = payload.change_preview(
        "Fill door %s from the transition details" % param, ["ElementId", "Mark", param], [param],
        before, after, notes=notes, warnings=warnings, recipe="door-thresholds",
        steps=[] if any(w.get("blocking") for w in warnings) else steps,
        ownership_ids=ids, edited_categories=["Doors"], expected_dependent_categories=[],
        not_changed=[d for d in analysis["doors"] if d["status"] != MATCH])
    return preview


def report_rows(analysis):
    return [[d["id"], d.get("mark"), d["from_room"], d.get("from_finish"), d["to_room"],
             d.get("to_finish"), ", ".join(d["refs"]), d["status"]] for d in analysis["doors"]]


REPORT_HEADERS = ["Id", "Mark", "From room", "From finish", "To room", "To finish", "Detail", "Status"]

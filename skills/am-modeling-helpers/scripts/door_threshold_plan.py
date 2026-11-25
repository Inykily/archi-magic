# -*- coding: utf-8 -*-
"""Plan door sill values from the floor finishes on both sides (issue #299).

Run from a terminal (CPython 3), not from Revit. Changes nothing.

Step 1, the code list and the detail names (to build the map with the user):
    python door_threshold_plan.py report --read doors.json --map finish-map.json [--format "{detail}/{sheet}"] [--out analysis.json]

Step 2, the change preview for am-safe-change (clear matches only):
    python door_threshold_plan.py preview --read doors.json --map finish-map.json --out preview.json

finish-map.json: {"confirmed": false, "codes": {"CPT": ["carpet"], "TZ": ["terrazzo"]},
                  "details": {"5/A-501": ["CPT", "TZ"]}}
Exit 0: OK. Exit 1: the preview is blocked. Exit 2: bad input.
"""
from __future__ import print_function

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import door_thresholds as dt  # noqa: E402
import payload  # noqa: E402


def load_map(path):
    try:
        with open(path, "r") as handle:
            data = json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        raise payload.InputError("Cannot read %s: %s" % (path, exc))
    return dt.load_map(data)


def print_report(analysis):
    print("Transition details (%d):" % len(analysis["details"]))
    print(payload.table([[d["ref"], d["view_name"], " + ".join(d["codes"]), d["pair"] or "NO PAIR",
                          d["source"]] for d in analysis["details"]],
                        ["Detail", "View name", "Codes found", "Pair", "From"]))
    print("Room finish codes: %s" % ", ".join("%s x%d" % kv for kv in sorted(analysis["room_codes"].items())))
    print(payload.table(dt.report_rows(analysis), dt.REPORT_HEADERS))
    print("Doors: %s." % ", ".join("%s %d" % (s, analysis["counts"][s]) for s in dt.STATUSES
                                   if s in analysis["counts"]))
    for w in analysis["warnings"]:
        print("%s: %s" % ("BLOCKING" if w.get("blocking") else "WARNING", w["text"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description="am-modeling-helpers door threshold plan")
    parser.add_argument("command", choices=["report", "preview"])
    parser.add_argument("--read", required=True, help="read_door_thresholds.py result JSON")
    parser.add_argument("--map", required=True, help="finish map JSON")
    parser.add_argument("--format", default=dt.DEFAULT_FORMAT, help="value format, default {detail}/{sheet}")
    parser.add_argument("--out", help="JSON file to write")
    args = parser.parse_args(argv)
    try:
        read = payload.load_read(args.read, dt.READ_KIND)
        analysis = dt.analyse(read, load_map(args.map), args.format)
    except payload.InputError as exc:
        print("ERROR: %s" % exc)
        return 2
    if not read.get("complete", True):
        print("WARNING: the read stopped at the door limit. Read fewer doors with door_ids.")
    if args.command == "report":
        print_report(analysis)
        if args.out:
            payload.write_json(args.out, analysis)
        return 0
    if not args.out:
        print("ERROR: preview needs --out.")
        return 2
    preview = dt.build_preview(analysis)
    payload.write_json(args.out, preview)
    print(payload.table([[b[0], b[1], b[2], a[2]] for b, a in zip(preview["before"], preview["after"])],
                        ["Id", "Mark", "Before", "After"]))
    for note in preview["notes"]:
        print(note)
    for w in preview["warnings"]:
        print("%s: %s" % ("BLOCKING" if w.get("blocking") else "WARNING", w["text"]))
    if preview["blocked"]:
        print("BLOCKED: do not offer Apply.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Check which room parameters a key schedule drives, and plan the change.

Run from a terminal (CPython 3), not from Revit.

Step 1, report (read only):

    python room_key_plan.py report --read keys.json --parameter "Floor Finish" [--out analysis.json]

Step 2, one change preview for one decision (am-safe-change format):

    python room_key_plan.py preview --read keys.json --parameter "Floor Finish"
        --value "<new value>" --option new-key --key <key id> --new-key-name "<name>"
        --out preview.json

Options: set-rooms (writable rooms), edit-key (one key row, all rooms that
use it change), new-key (copy the key row, assign it to the listed rooms).

Exit 0: OK. Exit 1: the preview is blocked, or the report found rooms that
need a key decision. Exit 2: bad input.
"""
from __future__ import print_function

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import payload  # noqa: E402
import room_keys  # noqa: E402


def print_report(analysis):
    print("Parameter: %s. Rooms: %s." % (analysis["parameter"], ", ".join(
        "%s %d" % (k, v) for k, v in sorted(analysis["counts"].items()))))
    rows = [[r["room_id"], r.get("number"), r.get("name"), r["state"], r.get("value"),
             r.get("key_name") or ""] for r in analysis["rooms"]]
    print(payload.table(rows, ["Id", "Number", "Name", "State", "Value", "Key"]))
    for g in analysis["groups"]:
        print("Key '%s' (%s, id %s): %d listed rooms, %d other rooms. Recommended: %s. %s" % (
            g["key_name"], g["key_parameter"], g["key_id"], len(g["target_room_ids"]),
            g["other_room_count"], g["recommended"], g["reason"]))
    for w in analysis["warnings"]:
        print("WARNING: %s" % w)


def main(argv=None):
    parser = argparse.ArgumentParser(description="am-modeling-helpers room key check")
    parser.add_argument("command", choices=["report", "preview"])
    parser.add_argument("--read", required=True, help="read_room_keys.py result JSON")
    parser.add_argument("--parameter", required=True, help="room parameter name, for example Floor Finish")
    parser.add_argument("--value", help="new value (preview)")
    parser.add_argument("--option", choices=[room_keys.SET_ROOMS, room_keys.EDIT_KEY, room_keys.NEW_KEY])
    parser.add_argument("--key", help="key id from the report (edit-key, new-key)")
    parser.add_argument("--new-key-name", help="name of the new key row (new-key)")
    parser.add_argument("--out", help="JSON file to write")
    args = parser.parse_args(argv)
    try:
        read = payload.load_read(args.read, "room-key-read")
        analysis = room_keys.analyze(read, args.parameter)
        if args.command == "report":
            if args.out:
                payload.write_json(args.out, analysis)
            print_report(analysis)
            return 1 if analysis["groups"] else 0
        if args.value is None or not args.option:
            raise payload.InputError("preview needs --value and --option.")
        if args.option != room_keys.SET_ROOMS and not args.key:
            raise payload.InputError("%s needs --key." % args.option)
        preview = room_keys.build_preview(read, analysis, args.option, args.value,
                                          key_id=args.key, new_key_name=args.new_key_name)
    except (payload.InputError, ValueError) as exc:
        print("room_key_plan: %s" % exc)
        return 2
    if args.out:
        payload.write_json(args.out, preview)
    print(preview["title"])
    rows = [b + [a[-1]] for b, a in zip(preview["before"], preview["after"])]
    print(payload.table(rows[:20], preview["columns"] + ["New value"]))
    if len(rows) > 20:
        print("... %d more rows in the preview file." % (len(rows) - 20))
    for note in preview["notes"]:
        print(note)
    for w in preview["warnings"]:
        print("%s: %s" % ("BLOCKED" if w.get("blocking") else "WARNING", w["text"]))
    return 1 if preview["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())

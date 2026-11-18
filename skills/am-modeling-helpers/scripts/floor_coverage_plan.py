# -*- coding: utf-8 -*-
"""Plan finish floor changes from a read_floor_room_coverage.py result.

Run from a terminal (CPython 3), not from Revit.

Step 1, summary and questions (read only):

    python floor_coverage_plan.py summary --read coverage.json
        [--finish-types <type id>,<type id>] [--out summary.json]

Step 2, one change preview for the user's decisions (am-safe-change format):

    python floor_coverage_plan.py preview --read coverage.json
        [--finish-types ...] --decide <floor id>=split,<floor id>=retype
        --new-type-id <type id> --new-type-name "<type name>" --out preview.json

Structural floors are never in a plan (user rule: never change the
structural slab). Exit 0: OK. Exit 1: the read is incomplete or the
preview is blocked. Exit 2: bad input.
"""
from __future__ import print_function

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import floor_coverage as fc  # noqa: E402
import payload  # noqa: E402


def parse_decisions(text):
    decisions = {}
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise payload.InputError("Write each decision as <floor id>=split|retype|skip.")
        floor_id, decision = [p.strip() for p in part.split("=", 1)]
        if not floor_id.isdigit() or decision not in (fc.SPLIT, fc.RETYPE, fc.SKIP):
            raise payload.InputError("Bad decision %r." % part)
        decisions[int(floor_id)] = decision
    if not decisions:
        raise payload.InputError("preview needs --decide.")
    return decisions


def print_summary(summary, asks):
    for note in summary["notes"]:
        print(note)
    rows = [[f["id"], f["type_name"], "yes" if f["is_structural"] else "", f["role"],
             f["top_area_sf"], payload.pct(f["share_in_scope"]), f["action"],
             ", ".join(str(r.get("number") or r["room_id"]) for r in f["rooms"])]
            for f in summary["floors"] if f["rooms"] or f["action"] == fc.UNRESOLVED]
    print(payload.table(rows, ["Floor", "Type", "Structural", "Role", "Area sf", "In scope", "Action", "Rooms"]))
    rows = [[r["id"], r.get("number"), r.get("area_sf"), payload.pct(r.get("coverage")), r["verdict"],
             ", ".join(str(f["floor_id"]) for f in r.get("finish_floors", []))]
            for r in summary["rooms"]]
    print(payload.table(rows, ["Room", "Number", "Area sf", "Finish cover", "Verdict", "Finish floors"]))
    for w in summary["warnings"]:
        print("WARNING: %s" % w)
    for n, ask in enumerate(asks, 1):
        print("Question %d: %s Options: %s (recommended: %s)." % (
            n, ask["text"], ", ".join(ask["options"]), ask["recommended"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description="am-modeling-helpers finish floor plan")
    parser.add_argument("command", choices=["summary", "preview"])
    parser.add_argument("--read", required=True, help="read_floor_room_coverage.py result JSON")
    parser.add_argument("--finish-types", help="comma-separated finish floor type ids")
    parser.add_argument("--decide", help="<floor id>=split|retype|skip, comma-separated")
    parser.add_argument("--new-type-id", type=int)
    parser.add_argument("--new-type-name")
    parser.add_argument("--out", help="JSON file to write")
    args = parser.parse_args(argv)
    try:
        read = payload.load_read(args.read, "floor-room-coverage-read")
        summary = fc.summarize(read, payload.parse_ids(args.finish_types))
        if args.command == "summary":
            asks = fc.questions(summary)
            summary["questions"] = asks
            if args.out:
                payload.write_json(args.out, summary)
            print_summary(summary, asks)
            return 0 if summary["complete"] else 1
        preview = fc.build_preview(summary, parse_decisions(args.decide),
                                   args.new_type_id, args.new_type_name)
    except payload.InputError as exc:
        print("floor_coverage_plan: %s" % exc)
        return 2
    if args.out:
        payload.write_json(args.out, preview)
    print(preview["title"])
    rows = [b + [a[-1]] for b, a in zip(preview["before"], preview["after"])]
    print(payload.table(rows[:20], preview["columns"] + ["New type"]))
    if len(rows) > 20:
        print("... %d more rows in the preview file." % (len(rows) - 20))
    for note in preview["notes"]:
        print(note)
    for w in preview["warnings"]:
        print("%s: %s" % ("BLOCKED" if w.get("blocking") else "WARNING", w["text"]))
    return 1 if preview["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())

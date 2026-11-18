# -*- coding: utf-8 -*-
"""Report sliver, ring and broken rooms from a read_room_shapes.py result.

Run from a terminal (CPython 3), not from Revit:

    python room_shape_report.py --read shapes.json [--out report.json]
        [--min-width-in 12] [--min-area-sf 2] [--area-tolerance 0.05]

Exit 0: no room is blocked. Exit 1: one or more rooms are not safe to model
finishes from (see the table). Exit 2: bad input.
"""
from __future__ import print_function

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import payload  # noqa: E402
import room_shape  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="am-modeling-helpers room shape check")
    parser.add_argument("--read", required=True, help="read_room_shapes.py result JSON")
    parser.add_argument("--out", help="report JSON to write")
    parser.add_argument("--min-width-in", type=float, default=12.0)
    parser.add_argument("--min-area-sf", type=float, default=room_shape.DEFAULT_RULES["min_area_sf"])
    parser.add_argument("--area-tolerance", type=float, default=room_shape.DEFAULT_RULES["area_tolerance"])
    args = parser.parse_args(argv)
    try:
        read = payload.load_read(args.read, "room-shape-read")
    except payload.InputError as exc:
        print("room_shape_report: %s" % exc)
        return 2
    rules = {"min_width_ft": args.min_width_in / 12.0, "min_area_sf": args.min_area_sf,
             "area_tolerance": args.area_tolerance}
    report = room_shape.report(read, rules)
    if args.out:
        payload.write_json(args.out, report)
    rows = []
    for row in report["rooms"]:
        if row["verdict"] == "ok":
            continue
        rows.append([row["id"], row.get("number"), row.get("name"), row["verdict"],
                     row.get("mean_width_in"), row.get("computed_area_sf"),
                     "; ".join(f["text"] for f in row["flags"])])
    for note in report["notes"]:
        print(note)
    if rows:
        print(payload.table(rows, ["Id", "Number", "Name", "Verdict", "Width in", "Area sf", "Findings"]))
    return 1 if report["counts"]["block"] else 0


if __name__ == "__main__":
    sys.exit(main())

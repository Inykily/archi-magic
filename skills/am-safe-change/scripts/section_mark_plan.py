# -*- coding: utf-8 -*-
"""Plan new detail sections from a plan markup (issue #257). Runs outside Revit.

    python section_mark_plan.py plan --marks marks.json --markers markers.json
        --bottom-z 0 --top-z 12 --depth 6 [--padding 1] [--tolerance-ft 1.0]
        [--max-angle 10] [--level-z 0] --out plan.json

marks.json: {"marks": [{"name": "M1", "start": [x, y], "end": [x, y],
                        "bar_side": [x, y]}, ...]}
  start and end are the ends of the cut line in plan (ft, model
  coordinates). bar_side is any point on the thick bar or the arrow of
  the mark. Give "look": [x, y] in place of bar_side when you know it.
markers.json: the result of read_section_markers.py (run_query).

It prints one row per mark: new or duplicate (with the existing marker
and the distance), the look direction, and the CreateDetail box. Marks
that duplicate an existing marker (or an earlier mark) get no box: the
same spot is never cut twice. Exit codes: 0 ok, 1 duplicates found (show
them to the user), 2 bad input.
Runs under CPython 3 and IronPython 2.7 (no f-strings).
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import section_marks as sm  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def bare(data):
    if isinstance(data, dict) and isinstance(data.get("response"), dict):
        data = data["response"]
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data


def build_plan(marks, markers, a):
    if a.level_z is not None:
        markers = sm.markers_at_level(markers, a.level_z)
    cuts = []
    for m in marks:
        if m.get("look"):
            look = [float(m["look"][0]), float(m["look"][1]), 0.0]
        else:
            look = sm.look_from_bar_side(m["start"], m["end"], m["bar_side"])
        cuts.append({"name": m["name"], "start": m["start"], "end": m["end"], "look": look})
    rows = sm.find_duplicates(cuts, markers, a.tolerance_ft, a.max_angle)
    out = []
    for cut, row in zip(cuts, rows):
        item = dict(row)
        item["look"] = cut["look"]
        item["start"], item["end"] = cut["start"], cut["end"]
        item["box"] = None if row["duplicate"] else sm.detail_box(
            cut["start"], cut["end"], cut["look"], a.bottom_z, a.top_z, a.depth, a.padding)
        out.append(item)
    return {"kind": "detail-section-plan", "tolerance_ft": a.tolerance_ft,
            "checked_markers": len(markers), "cuts": out}


def text_table(plan):
    out = ["%d mark(s), %d existing marker(s) checked, tolerance %.2f ft."
           % (len(plan["cuts"]), plan["checked_markers"], plan["tolerance_ft"])]
    for c in plan["cuts"]:
        look = "(%.3f, %.3f)" % (c["look"][0], c["look"][1])
        if c["duplicate"]:
            out.append("- %s: DUPLICATE of %s (%.2f ft, %.0f deg). No new section."
                       % (c["name"], c["duplicate_of"], c["distance"], c["angle"]))
        elif c["nearest"] is not None:
            out.append("- %s: new, look %s. Nearest marker %s at %.2f ft."
                       % (c["name"], look, c["nearest"], c["distance"]))
        else:
            out.append("- %s: new, look %s." % (c["name"], look))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan")
    p.add_argument("--marks", required=True)
    p.add_argument("--markers", required=True)
    p.add_argument("--bottom-z", type=float, required=True)
    p.add_argument("--top-z", type=float, required=True)
    p.add_argument("--depth", type=float, required=True)
    p.add_argument("--padding", type=float, default=0.0)
    p.add_argument("--tolerance-ft", type=float, default=1.0)
    p.add_argument("--max-angle", type=float, default=10.0)
    p.add_argument("--level-z", type=float)
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd != "plan":
        ap.print_help()
        return 2
    try:
        marks = bare(load_json(a.marks))
        marks = marks.get("marks") if isinstance(marks, dict) else marks
        markers = bare(load_json(a.markers))
        markers = markers.get("markers") if isinstance(markers, dict) else markers
        plan = build_plan(marks or [], markers or [], a)
    except (ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc)
        return 2
    with io.open(a.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(plan, indent=1, ensure_ascii=False))
    print(text_table(plan))
    return 1 if any(c["duplicate"] for c in plan["cuts"]) else 0


if __name__ == "__main__":
    sys.exit(main())

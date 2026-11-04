# -*- coding: utf-8 -*-
"""Offline coverage check for reference sample views.

Reads JSON and prints the coverage report and the fix plan. The JSON
shape is:

    {"model_types": {"Line Styles": ["A", "B"]},
     "samples": [{"category": "Line Styles", "label": "A",
                  "sample_type": "A"}],
     "rename_table": {"old name": "new name"},
     "no_sample": {"Line Styles": {"<Sketch>": "reason"}}}

"rename_table" and "no_sample" are optional. Give the JSON file path
as the first argument, or "-" to read stdin. The script always exits
0: it reports findings, it does not gate. The agent reads the report,
shows it to the user, and applies the plan only after approval.

Runs under IronPython 2.7 and CPython 3. No Revit imports. The open()
call sits inside a "with" statement, as the repo check requires.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import reference_samples as rs  # noqa: E402


def _load(path):
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r") as f:
        return json.load(f)


def _section(title):
    print("")
    print(title)


def _row_text(f):
    return ("[" + str(f["index"]) + "] " + f["category"] + ": label "
            + repr(f["label"]) + ", sample " + repr(f["sample_type"]))


def main(argv):
    if len(argv) < 2:
        print("usage: check_samples.py <samples.json | ->")
        return 2
    data = _load(argv[1])
    model_types = data.get("model_types", {})
    samples = data.get("samples", [])
    rename_table = data.get("rename_table", {})
    no_sample = data.get("no_sample", {})
    coverage = rs.check_coverage(model_types, samples)
    plan = rs.plan_fix(coverage, rename_table, model_types, no_sample,
                      samples)
    if coverage["clean"]:
        print("CLEAN: every type has one sample of its own type, "
              "and every label equals its sample name.")
    else:
        print("FINDINGS:")
    for cat in sorted(coverage["missing"]):
        for t in coverage["missing"][cat]:
            print("  MISSING: " + cat + ": no sample for " + repr(t))
    for f in coverage["unknown_labels"]:
        print("  UNKNOWN LABEL: " + _row_text(f))
    for d in coverage["duplicates"]:
        print("  DUPLICATE: " + d["category"] + ": sample "
              + repr(d["sample_type"]) + " appears "
              + str(len(d["indices"])) + " times, labels "
              + repr(d["labels"]))
    for f in coverage["mismatches"]:
        print("  MISMATCH: " + _row_text(f))
    _section("FIX PLAN (samples first, then labels):")
    for op in plan["sample_ops"]:
        print("  SET SAMPLE [" + str(op["index"]) + "] to "
              + repr(op["set_sample_to"]))
    for op in plan["create_ops"]:
        print("  CREATE SAMPLE: " + op["category"] + ": "
              + repr(op["type"]))
    for op in plan["remove_ops"]:
        print("  REMOVE SAMPLE [" + str(op["index"]) + "]: "
              + op["category"] + ": " + repr(op["sample_type"])
              + " (duplicate)")
    for op in plan["label_ops"]:
        print("  SET LABEL [" + str(op["index"]) + "] to "
              + repr(op["set_label_to"]))
    for row in plan["text_rows"]:
        print("  TEXT ROW: " + row["category"] + ": " + repr(row["type"])
              + " -- " + row["reason"])
    for f in plan["unfixable"]:
        print("  UNFIXABLE: [" + str(f["index"]) + "] "
              + f["category"] + ": label " + repr(f["label"]) + " -- "
              + f["reason"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

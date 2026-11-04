# -*- coding: utf-8 -*-
"""Build the fill-standards report from a read_fills.py read result.

CPython 3. Run from a terminal, not from Revit:

    python "<skill dir>\\scripts\\fill_report.py" --read read.json --out report.json

Exit 0 is OK. Exit 2 means bad input: the file path and the error are
printed, then the run stops. The report rules live in
scripts/lib/fill_standards.py. Do not change them by hand.

Optional --rules file (JSON): {"opq": "_OPQ", "trn": "_TRN"} to check
other suffix tokens against Masking. The defaults are the office
convention from the issue.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import fill_standards as fs  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="am-fill-standards report")
    parser.add_argument("--read", required=True, help="read_fills.py result JSON")
    parser.add_argument("--out", required=True, help="report JSON to write")
    parser.add_argument("--rules", help="optional suffix rules JSON")
    args = parser.parse_args(argv)
    try:
        with open(args.read, "r") as f:
            read_result = json.load(f)
    except (IOError, ValueError) as e:
        print("fill_report: cannot read %s: %s" % (args.read, e))
        return 2
    if "error" in read_result:
        print("fill_report: read result holds an error: %s" % (
            read_result.get("message", read_result["error"])))
        return 2
    rules = None
    if args.rules:
        try:
            with open(args.rules, "r") as f:
                rules = json.load(f)
        except (IOError, ValueError) as e:
            print("fill_report: cannot read rules %s: %s" % (args.rules, e))
            return 2
    rep = fs.report(read_result, rules)
    try:
        with open(args.out, "w") as f:
            json.dump(rep, f, indent=2, sort_keys=True)
    except IOError as e:
        print("fill_report: cannot write %s: %s" % (args.out, e))
        return 2
    print(fs.render_table(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())

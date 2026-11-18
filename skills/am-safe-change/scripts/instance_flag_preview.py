# -*- coding: utf-8 -*-
"""COMPUTE and COMPARE steps for the instance-flag recipe (issue #250). Runs outside Revit.

Compute the preview from a read_instance_flag.py result:
    python instance_flag_preview.py compute --read read.json --flag OVER
        --run-time "2026-11-18 14:30" [--decimals 2] [--scale 12 --unit " in"]
        [--title "..."] --out preview.json

The amount in the read result is in feet. --scale converts it to the
display unit (12 for inches, 304.8 for millimetres) and --unit is the
text after the number. The default is feet with no unit text.

Compare the apply result (dry run or real run) with the preview:
    python instance_flag_preview.py compare --preview preview.json --actual run.json

Exit codes: 0 ok, 1 differences or blocked, 2 bad input.
Runs under CPython 3 and IronPython 2.7 (no f-strings).
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import instance_flag as fl  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def actual_rows(data):
    if isinstance(data.get("response"), dict):
        data = data["response"]
    if "result" in data and "rows" not in data:
        data = data["result"]
    if data is None or "rows" not in data:
        raise ValueError("The result has no rows (check status and error).")
    return data["rows"], data


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("compute")
    c.add_argument("--read", required=True)
    c.add_argument("--flag", required=True)
    c.add_argument("--run-time", required=True)
    c.add_argument("--decimals", type=int, default=2)
    c.add_argument("--scale", type=float, default=1.0)
    c.add_argument("--unit", default="")
    c.add_argument("--title")
    c.add_argument("--out", required=True)
    v = sub.add_parser("compare")
    v.add_argument("--preview", required=True)
    v.add_argument("--actual", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "compute":
            read = fl.load_read_result(load_json(a.read))
            p = fl.plan_flags(read, a.flag, a.run_time, a.decimals, a.unit, a.scale, a.title)
            with io.open(a.out, "w", encoding="utf-8") as f:
                f.write(json.dumps(p, indent=1, ensure_ascii=False))
            print(fl.text_table(p))
            return 1 if p["blocked"] else 0
        if a.cmd == "compare":
            preview = load_json(a.preview)
            rows, result = actual_rows(load_json(a.actual))
            diffs = fl.compare(preview, rows)
            if result.get("shared_parameter_file_restored") is False:
                diffs.append("The shared parameter file setting was NOT restored. Tell the user "
                             "the old path: %r." % result.get("shared_parameter_file"))
            if diffs:
                print("DIFFERENT from preview (%d):" % len(diffs))
                for d in diffs:
                    print("  " + d)
                return 1
            print("MATCHES PREVIEW: %d value(s) checked." % len(preview["after"]))
            return 0
    except (ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc)
        return 2
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

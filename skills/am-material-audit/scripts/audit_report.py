# -*- coding: utf-8 -*-
"""COMPUTE step for the material audit. Runs outside Revit (CPython 3).

Build an audit table from a read_materials.py read result:
    python audit_report.py --read read.json [--out audit.json]

Input files may be the bare `result` object or the whole run JSON that
`pyrevit agent run` prints. Prints the table to stdout and, with --out,
writes the audit JSON. Exit codes: 0 ok, 2 bad input.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import material_audit as ma  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--read", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    try:
        data = load_json(a.read)
    except (IOError, ValueError) as e:
        print("ERROR: cannot read %s: %s" % (a.read, e))
        return 2
    try:
        result = ma.audit(data)
    except (KeyError, TypeError, ValueError) as e:
        print("ERROR: bad read result: %s" % e)
        return 2
    print(ma.render_table(result))
    if a.out:
        with io.open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

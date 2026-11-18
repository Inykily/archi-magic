# -*- coding: utf-8 -*-
"""VERIFY step for any am-safe-change run (issues #256 and #255). Runs outside Revit.

After Keep (or a commit under policy auto), re-read the changed elements
by element id with scripts/read_values_by_id.py (run_query), then:

    python verify_commit.py --preview preview.json --reread reread.json [--run run.json]

It prints one line that the final summary must carry, for example
    Verified by re-read: 23 of 23 elements match the preview (by element id).
or
    Not verified: 3 of 23 elements differ from the preview; 1 not found by id.
and then each difference. --run is the saved record of the real run:
its decision must be "committed" and "failures" must hold no Error.

Input files may be the bare result or the saved run record.
Exit codes: 0 verified, 1 not verified, 2 bad input.
Runs under CPython 3 and IronPython 2.7 (no f-strings).
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import commit_verify as cv  # noqa: E402
import run_checks as checks  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def bare_result(data):
    data = checks.unwrap_run(data)
    if isinstance(data.get("result"), dict) and "rows" not in data:
        return data["result"]
    return data


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", required=True)
    ap.add_argument("--reread", required=True)
    ap.add_argument("--run")
    ap.add_argument("--tolerance", type=float, default=1e-6)
    a = ap.parse_args(argv)
    try:
        preview = load_json(a.preview)
        reread = bare_result(load_json(a.reread))
        run = load_json(a.run) if a.run else None
        report = cv.verify(preview, reread, run, a.tolerance)
    except (ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc)
        return 2
    print(cv.verify_text(report))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())

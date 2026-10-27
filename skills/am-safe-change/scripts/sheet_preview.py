# -*- coding: utf-8 -*-
"""COMPUTE and VERIFY steps for the sheet renumber recipe. Runs outside Revit (CPython 3).

Compute a preview from a read_sheets.py result:
    python sheet_preview.py compute --read read.json --start A301 [--step 1]
        [--scope series|after|custom] [--ids 1,2,3] [--close-gaps]
        [--no-suffixed] [--no-placeholders] [--title "..."] --out preview.json

Compare a later result (apply dry run, or a fresh read) with the preview:
    python sheet_preview.py compare --preview preview.json --actual run.json

Show the side-effect counts of a dry run (issue #28):
    python sheet_preview.py side-effects --preview preview.json --dryrun dryrun.json

Input files may be the bare `result` object or the whole run JSON that
`pyrevit agent run` prints. Exit codes: 0 ok, 1 differences or blocked, 2 bad input.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import sheet_shift as ss  # noqa: E402
import side_effects as se  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def actual_rows(data):
    """Rows [id, number] from an apply result or a read result."""
    if "result" in data and "sheets" not in data and "rows" not in data:
        data = data["result"]
    if data is None:
        raise ValueError("The run has no result (check status and error).")
    if "rows" in data:
        rows = [[r[0], ss.unescape(r[1]) if data.get("escaped") else r[1]] for r in data["rows"]]
        return rows, data.get("partial", False)
    return [[s["id"], s["number"]] for s in ss.load_read_result(data)], False


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("compute")
    c.add_argument("--read", required=True)
    c.add_argument("--start", required=True)
    c.add_argument("--step", type=int, default=1)
    c.add_argument("--scope", default="series", choices=["series", "after", "custom"])
    c.add_argument("--ids", default="")
    c.add_argument("--close-gaps", action="store_true")
    c.add_argument("--no-suffixed", action="store_true")
    c.add_argument("--no-placeholders", action="store_true")
    c.add_argument("--title")
    c.add_argument("--out", required=True)
    v = sub.add_parser("compare")
    v.add_argument("--preview", required=True)
    v.add_argument("--actual", required=True)
    s = sub.add_parser("side-effects")
    s.add_argument("--preview", required=True)
    s.add_argument("--dryrun", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "compute":
        sheets = ss.load_read_result(load_json(a.read))
        ids = [int(x) for x in a.ids.split(",") if x.strip()]
        p = ss.compute_shift(sheets, a.start, a.step, a.scope, not a.close_gaps,
                             not a.no_suffixed, not a.no_placeholders, ids, a.title)
        with io.open(a.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(p, indent=1, ensure_ascii=False))
        print(ss.text_table(p))
        return 1 if p["blocked"] else 0
    if a.cmd == "compare":
        preview = load_json(a.preview)
        rows, partial = actual_rows(load_json(a.actual))
        if partial:
            # apply returns only the sheets it touched: compare those rows only.
            ids = set(r[0] for r in rows)
            preview = dict(preview)
            preview["after"] = [r for r in preview["after"] if r[0] in ids]
        diffs = ss.compare(preview, rows)
        if diffs:
            print("DIFFERENT from preview (%d):" % len(diffs))
            for d in diffs:
                print("  " + d)
            return 1
        print("MATCHES PREVIEW: %d sheets checked." % len(rows))
        return 0
    if a.cmd == "side-effects":
        preview = load_json(a.preview)
        summary = se.summarize(preview, load_json(a.dryrun), ["Sheets"])
        print(se.text_table(summary))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

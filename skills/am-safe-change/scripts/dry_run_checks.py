# -*- coding: utf-8 -*-
"""Dry-run checks for am-safe-change (issues #256 and #255). Runs outside Revit.

Content checks (new elements in the view, tag text, leader ends, values
read after doc.Regenerate()):
    python dry_run_checks.py content --dryrun dryrun.json [--max-leader-ft 3]

Read the change list (name every changed annotation, stop on an
unexpected or uncategorized category):
    python dry_run_checks.py change-list --preview preview.json --dryrun dryrun.json
        [--annotations annotations.json]

Join the annotation text before (read_values_by_id.py with the column
"Text") and after (a second dry run that returns content for those ids):
    python dry_run_checks.py annotation-text --before before.json --after dryrun2.json
        --out annotations.json

Errors in "failures" (also for a committed run):
    python dry_run_checks.py failures --run run.json

The dry-run file is the saved run record, the bare result, or the
"content" object itself. See recipes/check-and-verify.md for the shapes.
Exit codes: 0 clean; 1 a warning or a stop (show it to the user, do not
apply without their answer, and never report the change as done);
2 bad input.
Runs under CPython 3 and IronPython 2.7 (no f-strings).
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import run_checks as checks  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def extract_content(data):
    """The content dict from a run record, a bare result, or the content itself."""
    data = checks.unwrap_run(data)
    if isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data.get("content"), dict):
        return data["content"]
    if any(k in data for k in ("elements", "tags", "values", "view")):
        return data
    raise ValueError("No dry-run content found. The apply script must return a "
                     "'content' object (see recipes/check-and-verify.md).")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("content")
    c.add_argument("--dryrun", required=True)
    c.add_argument("--max-leader-ft", type=float, default=3.0)
    r = sub.add_parser("change-list")
    r.add_argument("--preview", required=True)
    r.add_argument("--dryrun", required=True)
    r.add_argument("--annotations")
    t = sub.add_parser("annotation-text")
    t.add_argument("--before", required=True)
    t.add_argument("--after", required=True)
    t.add_argument("--out", required=True)
    f = sub.add_parser("failures")
    f.add_argument("--run", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "content":
            report = checks.content_report(extract_content(load_json(a.dryrun)), a.max_leader_ft)
            print(checks.content_text(report))
            return 1 if report["warnings"] else 0
        if a.cmd == "change-list":
            annotations = None
            if a.annotations:
                annotations = load_json(a.annotations)
                if isinstance(annotations, dict):
                    annotations = annotations.get("annotations") or annotations.get("rows") or []
            review = checks.review_change_list(load_json(a.dryrun), load_json(a.preview), annotations)
            print(checks.change_list_text(review))
            return 1 if review["blocking"] else 0
        if a.cmd == "annotation-text":
            before = checks.unwrap_run(load_json(a.before))
            if isinstance(before.get("result"), dict):
                before = before["result"]
            rows = checks.annotation_rows(before, extract_content(load_json(a.after)).get("tags"))
            with io.open(a.out, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"annotations": rows}, indent=1, ensure_ascii=False))
            print("Wrote %d annotation row(s) to %s." % (len(rows), a.out))
            return 0
        if a.cmd == "failures":
            run = load_json(a.run)
            print(checks.failures_text(run))
            return 1 if checks.failure_errors(run) else 0
    except (ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc)
        return 2
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

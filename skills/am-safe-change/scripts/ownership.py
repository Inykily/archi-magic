# -*- coding: utf-8 -*-
"""Worksharing ownership steps for every am-safe-change recipe (issue #97, CPython 3).

Write the inputs for read_ownership.py (target ids from the preview steps):
    python ownership.py inputs --preview preview.json [--ids 123,456] --out own-inputs.json
After the run, add the dry run's categories, so the read also finds borrowed dependents:
    python ownership.py inputs --preview preview.json --dryrun dryrun.json --out own-inputs.json

Check the read before the dry run. Adds the ownership line and blocking warnings to the preview:
    python ownership.py check --read own.json --preview preview.json [--out preview.json]

Report what the current user borrows after a kept or discarded run:
    python ownership.py borrowed --read own.json

Input files may be the bare `result` object or the whole run JSON that
`pyrevit agent run` prints. Exit codes: 0 ok, 1 blocked (owned by others or
updated in central), 2 bad input.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import ownership as ow  # noqa: E402
import side_effects as se  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, data):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=1, ensure_ascii=False))


def id_list(text):
    return [int(x) for x in (text or "").split(",") if x.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    i = sub.add_parser("inputs")
    i.add_argument("--preview", required=True)
    i.add_argument("--ids", default="")
    i.add_argument("--dryrun")
    i.add_argument("--max-elements", type=int, default=5000)
    i.add_argument("--out", required=True)
    c = sub.add_parser("check")
    c.add_argument("--read", required=True)
    c.add_argument("--preview")
    c.add_argument("--out")
    b = sub.add_parser("borrowed")
    b.add_argument("--read", required=True)
    a = ap.parse_args(argv)

    try:
        if a.cmd == "inputs":
            ids = ow.target_ids(load_json(a.preview), id_list(a.ids))
            if not ids:
                print("No target ids in the preview. Pass them with --ids.")
                return 2
            data = {"ids": ids, "max_elements": a.max_elements}
            if a.dryrun:
                dry = se.unwrap_dryrun(load_json(a.dryrun))
                data["categories"] = sorted((dry.get("modified_by_category") or {}).keys())
            write_json(a.out, data)
            print("Wrote %s: %d target id(s), %d categor(ies) to scan."
                  % (a.out, len(ids), len(data.get("categories") or [])))
            return 0
        if a.cmd == "check":
            summary = ow.check(load_json(a.read))
            print(ow.text_table(summary))
            if a.preview:
                out = a.out or a.preview
                write_json(out, ow.annotate(load_json(a.preview), summary))
                print("Wrote %s." % out)
            return 1 if summary["blocked"] else 0
        if a.cmd == "borrowed":
            print(ow.borrowed(load_json(a.read))["line"])
            return 0
    except (ValueError, KeyError) as e:
        print("Bad input: %s" % e)
        return 2
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

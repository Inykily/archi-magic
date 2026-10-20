# -*- coding: utf-8 -*-
"""VALIDATE, COMPUTE and COMPARE steps for the element-transforms recipe (CPython 3).

Validate a pasted request (no Revit needed):
    python transforms_preview.py validate --request transforms.json

Compute a preview from the request and a read_elements.py result:
    python transforms_preview.py compute --request transforms.json --read read.json
        [--skip 123,456] [--accept hosted,hosts_others] [--title "..."] --out preview.json

Compare a later result (apply dry run, or a fresh read) with the preview:
    python transforms_preview.py compare --preview preview.json --actual run.json

Input files may be the bare `result` object or the whole run JSON that
`pyrevit agent run` prints. Exit codes: 0 ok, 1 differences or blocked, 2 bad input.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import transforms as tf  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def id_list(text):
    return [int(x) for x in (text or "").split(",") if x.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    v = sub.add_parser("validate")
    v.add_argument("--request", required=True)
    c = sub.add_parser("compute")
    c.add_argument("--request", required=True)
    c.add_argument("--read", required=True)
    c.add_argument("--skip", default="")
    c.add_argument("--accept", default="")
    c.add_argument("--title")
    c.add_argument("--out", required=True)
    m = sub.add_parser("compare")
    m.add_argument("--preview", required=True)
    m.add_argument("--actual", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "validate":
        items, errors = tf.validate_request(load_json(a.request))
        if errors:
            print("INVALID request (%d):" % len(errors))
            for e in errors:
                print("  " + e)
            return 2
        print("VALID: %d item(s): %s" % (len(items), ", ".join(str(i["id"]) for i in items)))
        return 0
    if a.cmd == "compute":
        elements, unit = tf.load_read_result(load_json(a.read))
        accept = [x.strip() for x in a.accept.split(",") if x.strip()]
        try:
            p = tf.compute_preview(load_json(a.request), elements, unit,
                                   id_list(a.skip), accept, a.title)
        except ValueError as e:
            print(str(e))
            return 2
        with io.open(a.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(p, indent=1, ensure_ascii=False))
        print(tf.text_table(p))
        need = tf.decisions_needed(p)
        if need:
            print("")
            print("Decisions needed (one question per type):")
            for k in sorted(need):
                print("  %s: %s" % (k, ", ".join(need[k])))
        return 1 if p["blocked"] else 0
    if a.cmd == "compare":
        preview = load_json(a.preview)
        actual = tf.actual_from(load_json(a.actual))
        ids = set(st["id"] for st in preview.get("steps") or [])
        actual = dict((k, v) for k, v in actual.items() if k in ids or not ids)
        diffs = tf.compare(preview, actual)
        if diffs:
            print("DIFFERENT from preview (%d):" % len(diffs))
            for d in diffs:
                print("  " + d)
            return 1
        print("MATCHES PREVIEW: %d elements checked." % len(preview.get("steps") or []))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

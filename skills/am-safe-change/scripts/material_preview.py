# -*- coding: utf-8 -*-
"""COMPUTE, PALETTE and COMPARE steps for the material-colors recipe (CPython 3).

Compute a preview from a panel request and a read_materials.py result:
    python material_preview.py compute --request colors.json --read read.json
        [--title "..."] --out preview.json

Suggest light greys that stay readable (WCAG ratios):
    python material_preview.py palette --count 5 [--foreground 90,90,90]

Compare a later result (apply dry run, or a fresh read) with the preview:
    python material_preview.py compare --preview preview.json --actual run.json

Show the side-effect counts of a dry run (issue #28):
    python material_preview.py side-effects --preview preview.json --dryrun dryrun.json

Input files may be the bare `result` object or the whole run JSON that
`pyrevit agent run` prints. Exit codes: 0 ok, 1 differences or blocked, 2 bad input.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import material_colors as mc  # noqa: E402
import side_effects as se  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def rgb_list(text):
    return [int(x) for x in (text or "").split(",") if x.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("compute")
    c.add_argument("--request", required=True)
    c.add_argument("--read", required=True)
    c.add_argument("--title")
    c.add_argument("--out", required=True)
    p = sub.add_parser("palette")
    p.add_argument("--count", type=int, required=True)
    p.add_argument("--foreground", default="0,0,0")
    m = sub.add_parser("compare")
    m.add_argument("--preview", required=True)
    m.add_argument("--actual", required=True)
    s = sub.add_parser("side-effects")
    s.add_argument("--preview", required=True)
    s.add_argument("--dryrun", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "compute":
        materials = mc.load_read_result(load_json(a.read))
        try:
            pv = mc.compute_preview(load_json(a.request), materials, a.title)
        except ValueError as e:
            print(str(e))
            return 2
        with io.open(a.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(pv, indent=1, ensure_ascii=False))
        print(mc.text_table(pv))
        return 1 if pv["blocked"] else 0
    if a.cmd == "palette":
        fg = rgb_list(a.foreground)
        if len(fg) != 3 or not mc._is_rgb(fg):
            print("Foreground must be an RGB list (0-255): %s" % a.foreground)
            return 2
        try:
            greys = mc.suggest_greys(a.count, fg)
        except ValueError as e:
            print(str(e))
            return 2
        print(mc.palette_table(greys, fg))
        return 0
    if a.cmd == "compare":
        preview = load_json(a.preview)
        try:
            actual = mc.actual_from(load_json(a.actual))
        except ValueError as e:
            print(str(e))
            return 2
        diffs = mc.compare(preview, actual)
        if diffs:
            print("DIFFERENT from preview (%d):" % len(diffs))
            for d in diffs:
                print("  " + d)
            return 1
        print("MATCHES PREVIEW: %d materials checked." % len(preview.get("steps") or []))
        return 0
    if a.cmd == "side-effects":
        preview = load_json(a.preview)
        summary = se.summarize(preview, load_json(a.dryrun), ["Materials"])
        print(se.text_table(summary))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

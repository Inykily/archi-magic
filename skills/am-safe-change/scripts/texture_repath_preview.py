# -*- coding: utf-8 -*-
"""COMPUTE / COMPARE / SIDE-EFFECTS for the texture-repath recipe.

Runs outside Revit (CPython 3):

    python texture_repath_preview.py compute --read audit.json
        --folder <project texture folder> --out preview.json
    python texture_repath_preview.py compare --preview preview.json
        --actual verify.json
    python texture_repath_preview.py compare-dryrun --preview preview.json
        --actual dryrun.json
    python texture_repath_preview.py side-effects --preview preview.json
        --dryrun dryrun.json

--read is the audit JSON that texture_report.py writes. --folder is
this project's folder only: the proposal index is built from that
folder alone, so no file from another project can be proposed.

compute prints a chat table and writes the change preview. compare
prints MATCHES PREVIEW (exit 0) or DIFFERENT with each difference
(exit 1), and compare-dryrun does the same for a dry-run result.
side-effects prints the edited vs regenerated counts from
the dry-run result (exit 0).
"""
import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import texture_repath as tr  # noqa: E402
import side_effects as se  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, data):
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def chat_table(preview):
    """Compact preview table for chat: first 10 and last 10 changed rows."""
    changed = [(b, a) for b, a in zip(preview.get("before") or [],
                                      preview.get("after") or [])
               if tr.normalize_path(b[5]) != tr.normalize_path(a[5])]
    lines = ["Repath texture images: %d slots change." % len(changed)]
    for i, (before, after) in enumerate(changed):
        if len(changed) > 20 and i == 10:
            lines.append("... (%d more rows)" % (len(changed) - 20))
        if len(changed) > 20 and 10 <= i < len(changed) - 10:
            continue
        lines.append("%s / %s: %s -> %s"
                     % (after[1], after[3], after[4], after[5]))
    for note in preview.get("notes") or []:
        lines.append(note)
    for w in preview.get("warnings") or []:
        lines.append("%s: %s" % ("BLOCKING" if w.get("blocking") else "WARN",
                                 w.get("text")))
    if preview.get("not_found"):
        lines.append("%d slots have no file in the search folder "
                     "(see not_found in the preview)." % len(preview["not_found"]))
    if preview.get("needs_choice"):
        lines.append("%d slots have more than one candidate "
                     "(see needs_choice in the preview)."
                     % len(preview["needs_choice"]))
    return "\n".join(lines)


def cmd_compute(a):
    try:
        audit = load_json(a.read)
    except (IOError, ValueError) as e:
        print("ERROR: cannot read %s: %s" % (a.read, e))
        return 2
    if not os.path.isdir(a.folder):
        print("ERROR: search folder does not exist: %s" % a.folder)
        return 2
    preview = tr.compute_preview(audit, tr.build_index(tr.scan_folder(a.folder)),
                                 a.folder)
    print(chat_table(preview))
    if a.out:
        write_json(a.out, preview)
    return 0


def cmd_compare(a):
    try:
        preview = load_json(a.preview)
        actual = load_json(a.actual)
    except (IOError, ValueError) as e:
        print("ERROR: cannot read input: %s" % e)
        return 2
    matches, differences = tr.compare_preview(preview, actual)
    if matches:
        print("MATCHES PREVIEW")
        return 0
    print("DIFFERENT")
    for d in differences:
        print("  " + d)
    return 1


def cmd_compare_dryrun(a):
    try:
        preview = load_json(a.preview)
        actual = load_json(a.actual)
    except (IOError, ValueError) as e:
        print("ERROR: cannot read input: %s" % e)
        return 2
    matches, differences = tr.compare_dryrun(preview, actual)
    if matches:
        print("MATCHES PREVIEW")
        return 0
    print("DIFFERENT")
    for d in differences:
        print("  " + d)
    return 1


def cmd_side_effects(a):
    try:
        preview = load_json(a.preview)
        dryrun = load_json(a.dryrun)
    except (IOError, ValueError) as e:
        print("ERROR: cannot read input: %s" % e)
        return 2
    summary = se.summarize(preview, dryrun, ["Materials"])
    print(se.text_table(summary))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("compute")
    c.add_argument("--read", required=True)
    c.add_argument("--folder", required=True)
    c.add_argument("--out", default="")
    m = sub.add_parser("compare")
    m.add_argument("--preview", required=True)
    m.add_argument("--actual", required=True)
    d = sub.add_parser("compare-dryrun")
    d.add_argument("--preview", required=True)
    d.add_argument("--actual", required=True)
    s = sub.add_parser("side-effects")
    s.add_argument("--preview", required=True)
    s.add_argument("--dryrun", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "compute":
        return cmd_compute(a)
    if a.cmd == "compare":
        return cmd_compare(a)
    if a.cmd == "compare-dryrun":
        return cmd_compare_dryrun(a)
    if a.cmd == "side-effects":
        return cmd_side_effects(a)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

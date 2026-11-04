# -*- coding: utf-8 -*-
"""COMPUTE step for the texture-path audit. Runs outside Revit (CPython 3).

Classify the slots of a read_texture_paths.py read result:
    python texture_report.py --read read.json [--out audit.json]
                             [--library-dir DIR ...]

Input files may be the bare `result` object or the whole run JSON that
`pyrevit agent run` prints. Prints the table to stdout and, with --out,
writes the audit JSON. Exit codes: 0 ok, 2 bad input.

--library-dir names a folder of installed Autodesk library textures; its
file names (any depth) resolve stored paths by file name alone. Repeat
it for every library home. The default is both Program Files homes of
the Autodesk shared material library; homes that do not exist are
skipped, so the same command works on a machine without Revit.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import texture_paths as tp  # noqa: E402

DEFAULT_LIBRARY_DIRS = (
    "C:\\Program Files\\Common Files\\Autodesk Shared\\Materials\\Textures",
    "C:\\Program Files (x86)\\Common Files\\Autodesk Shared\\Materials\\Textures",
)


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def library_names(dirs):
    """Lower-cased file names found under the given folders, any depth."""
    names = set()
    for folder in dirs:
        if not folder or not os.path.isdir(folder):
            continue
        for root, _dirs, files in os.walk(folder):
            for name in files:
                names.add(name.lower())
    return names


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--read", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--library-dir", action="append", default=[])
    a = ap.parse_args(argv)
    try:
        data = load_json(a.read)
    except (IOError, ValueError) as e:
        print("ERROR: cannot read %s: %s" % (a.read, e))
        return 2
    try:
        result = tp.audit_texture_paths(
            data, os.path.isfile,
            library_names(a.library_dir or DEFAULT_LIBRARY_DIRS))
    except (KeyError, TypeError, ValueError) as e:
        print("ERROR: bad read result: %s" % e)
        return 2
    print(tp.render_table(result))
    if a.out:
        with io.open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Index and search a local Revit family library without Revit (CPython 3).

Build or refresh the index of one library folder:
    python family_library.py index <library-folder> --out index.json
        [--thumbnails <folder>] [--previous index.json]
        [--max-entries 50000] [--max-depth 16]

Search the index:
    python family_library.py search index.json [--text "door single"]
        [--category doors] [--type 900] [--param "Width=900"]
        [--in-model loaded.json] [--include-backups] [--include-unreadable]
        [--limit 50] [--out results.json]

--in-model takes the saved result of read_loaded_families.py (run_query)
and marks which results are already in the open model.

The library files are only read, never changed. Keep the index, the
thumbnails and the results on your computer: they contain file paths.

Exit codes: index 0 complete, 1 partial (see "skipped"), 2 bad input.
search 0 rows found, 1 no rows, 2 bad input.
"""
from __future__ import print_function

import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import family_index as fi  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def summary_lines(index):
    counts = index["counts"]
    lines = ["Indexed %d families with %d types in %s." % (
        counts["families"], counts["types"], index["root"])]
    if counts["reused"]:
        lines.append("%d families were unchanged and reused from the previous index." % counts["reused"])
    for status, number in sorted(counts["by_status"].items()):
        if status != "ok":
            lines.append("%d families: %s." % (number, status.replace("_", " ")))
    for reason, number in sorted(counts["skipped"].items()):
        lines.append("Skipped %d: %s." % (number, reason.replace("_", " ")))
    if index["limits_hit"]:
        lines.append("Limits hit: %s. The index is partial." % ", ".join(index["limits_hit"]))
    elif not index["complete"]:
        lines.append("The index is partial. Read the skipped list.")
    else:
        lines.append("The index is complete.")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description="Index and search a local Revit family library.")
    commands = parser.add_subparsers(dest="command")
    build = commands.add_parser("index")
    build.add_argument("root")
    build.add_argument("--out", required=True)
    build.add_argument("--thumbnails")
    build.add_argument("--previous")
    build.add_argument("--max-entries", type=int, default=fi.MAX_ENTRIES)
    build.add_argument("--max-depth", type=int, default=fi.MAX_DEPTH)
    find = commands.add_parser("search")
    find.add_argument("index")
    find.add_argument("--text")
    find.add_argument("--category")
    find.add_argument("--type", dest="type_name")
    find.add_argument("--param")
    find.add_argument("--in-model")
    find.add_argument("--include-backups", action="store_true")
    find.add_argument("--include-unreadable", action="store_true")
    find.add_argument("--limit", type=int, default=50)
    find.add_argument("--out")
    args = parser.parse_args(argv)

    try:
        if args.command == "index":
            previous = None
            if args.previous and os.path.isfile(args.previous):
                previous = fi.load_index(args.previous)
            index = fi.build_index(args.root, args.thumbnails, previous,
                                   args.max_entries, args.max_depth)
            fi.write_index(index, args.out)
            print("\n".join(summary_lines(index)))
            return 0 if index["complete"] else 1
        if args.command == "search":
            index = fi.load_index(args.index)
            result = fi.search(index, args.text, args.category, args.type_name,
                               fi.parse_parameter_filter(args.param),
                               args.include_backups, args.include_unreadable, args.limit)
            show_model = bool(args.in_model)
            if show_model:
                marked = fi.mark_in_model(result["rows"], load_json(args.in_model))
                result["rows"] = marked["rows"]
                result["model_read_truncated"] = marked["truncated"]
            if args.out:
                with io.open(args.out, "w", encoding="utf-8") as f:
                    f.write(json.dumps(result, ensure_ascii=False, indent=1))
            print(fi.text_table(result, show_model))
            if not index.get("complete"):
                print("Note: the index is partial, so a family can be missing from the results.")
            if result.get("model_read_truncated"):
                print("Note: the model read hit its limit, so 'In model' can be incomplete.")
            return 0 if result["rows"] else 1
    except (ValueError, OSError) as exc:
        print("Family library: %s" % exc, file=sys.stderr)
        return 2
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

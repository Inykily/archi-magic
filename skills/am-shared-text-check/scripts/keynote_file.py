"""Audit Revit keynote keys and stage an edited text file with a backup."""

import argparse
from collections import defaultdict
import codecs
import json
from pathlib import Path
import sys


def parse_keynotes(data):
    encoding = "utf-16" if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
    entries = {}
    children = defaultdict(list)
    for line, raw in enumerate(data.decode(encoding).splitlines(), 1):
        if not raw.strip():
            continue
        fields = [field.strip() for field in raw.split("\t")]
        if len(fields) not in (2, 3) or not all(fields[:2]):
            raise ValueError(f"line {line} must contain a key and description and may contain a parent")
        key, description = fields[:2]
        parent = fields[2] or None if len(fields) == 3 else None
        if key in entries:
            raise ValueError(f"line {line} duplicates a keynote key")
        entries[key] = {"key": key, "description": description, "parent": parent}
        children[parent].append(key)
    if not entries:
        raise ValueError("the keynote file has no entries")
    for entry in entries.values():
        if entry["parent"] is not None and entry["parent"] not in entries:
            raise ValueError(f"key {entry['key']} names a missing parent")

    tree = []
    pending = [(key, 0) for key in reversed(children[None])]
    while pending:
        key, depth = pending.pop()
        tree.append(dict(entries[key], depth=depth))
        pending.extend((child, depth + 1) for child in reversed(children[key]))
    if len(tree) != len(entries):
        raise ValueError("the keynote file contains a parent cycle")
    return entries, tree


def read_usage(path):
    with path.open(encoding="utf-8-sig") as stream:
        usage = json.load(stream)
    if not isinstance(usage, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("key"), str) or not row["key"].strip()
        or not isinstance(row.get("tag_id"), (int, str)) or isinstance(row["tag_id"], bool)
        or not str(row["tag_id"]).strip()
        for row in usage
    ):
        raise ValueError("tag usage must be a JSON list of objects with nonempty tag_id and key")
    return [{"tag_id": row["tag_id"], "key": row["key"].strip()} for row in usage]


def audit(data, usage):
    entries, tree = parse_keynotes(data)
    missing = [row for row in usage if row["key"] not in entries]
    used = {row["key"] for row in usage}
    parent_keys = {row["parent"] for row in tree if row["parent"] is not None}
    return {
        "tree": tree,
        "tags_checked": len(usage),
        "missing_tags": missing,
        "unused_leaf_keys": sorted(entries.keys() - used - parent_keys),
    }


def write_new(path, data):
    # Exclusive creation keeps the source and existing outputs intact.
    with path.open("xb") as stream:
        try:
            stream.write(data)
            stream.flush()
        except OSError:
            stream.close()
            path.unlink(missing_ok=True)
            raise


def stage(args, source, usage):
    candidate = args.candidate.read_bytes()
    previous = audit(source, usage)
    updated = audit(candidate, usage)
    previous_missing = {row["key"] for row in previous["missing_tags"]}
    newly_missing = {row["key"] for row in updated["missing_tags"]} - previous_missing
    if newly_missing:
        raise ValueError("the edited file removes keys referenced by tags: " + ", ".join(sorted(newly_missing)))
    if args.output == args.backup:
        raise ValueError("output and backup must have different paths")
    write_new(args.backup, source)
    try:
        write_new(args.output, candidate)
    except OSError:
        print("The source backup was saved before staging failed.", file=sys.stderr)
        raise
    return updated


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("audit", "stage"):
        command = sub.add_parser(name)
        command.add_argument("--keynotes", type=Path, required=True)
        command.add_argument("--usage", type=Path, required=True)
        if name == "stage":
            for field in ("candidate", "output", "backup"):
                command.add_argument("--" + field, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source = args.keynotes.read_bytes()
        usage = read_usage(args.usage)
        result = stage(args, source, usage) if args.action == "stage" else audit(source, usage)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 1 if result["missing_tags"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

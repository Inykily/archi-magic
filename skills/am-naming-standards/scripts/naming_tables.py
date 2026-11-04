# -*- coding: utf-8 -*-
"""COMPUTE step for the naming-standards skill. Runs outside Revit (CPython 3).

Build a rename table, a filter scan, delete flags and a
reference-view label plan from a naming_inventory.py read result
plus a rule set:

    python naming_tables.py --read inventory.json --rules rules.json [--out tables.json]

Input files may be the bare `result` object or the whole run JSON
that `pyrevit agent run` prints. Prints the tables to stdout and,
with --out, writes the tables JSON. Exit codes: 0 ok, 2 bad input.

Rules JSON shape (see naming_rules.py): case, separator,
acronyms, allow_parens, prefixes, scale_style.
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import naming_rules as nr  # noqa: E402


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def unwrap(data):
    """Accept a bare result object or a full run JSON."""
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data


def build_tables(inventory, rules):
    """All four tables from one inventory read and one rule set."""
    rows = inventory.get("rows", [])
    table = nr.build_rename_table(rows, rules)
    old_names = [r["name"] for r in rows]
    filters = scan_filters(inventory)
    refs = nr.scan_filter_refs(filters, old_names)
    deletes = []
    for row in rows:
        flags = nr.check_delete(
            row, inventory.get("unplaced_group_types", []),
            inventory.get("placed_group_members", {}))
        if flags:
            deletes.append({"id": row["id"], "name": row["name"],
                            "flags": flags})
    rename_map = dict((r["old"], r["new"]) for r in table)
    labels = nr.plan_reference_labels(
        inventory.get("reference_views", []), rename_map)
    paren_blockers = [r for r in table
                      if "data_part_has_parens" in r["flags"]]
    return {"rename_table": table, "filter_refs": refs,
            "delete_flags": deletes, "label_plan": labels,
            "paren_blockers": paren_blockers,
            "not_checked": inventory.get("not_checked", [])}


def scan_filters(inventory):
    """View filters plus schedule filters, one list for the scan."""
    out = []
    for f in inventory.get("view_filters", []):
        item = dict(f)
        item["kind"] = "view_filter"
        out.append(item)
    for f in inventory.get("schedule_filters", []):
        item = dict(f)
        item["kind"] = "schedule_filter"
        out.append(item)
    return out


def render_text(tables):
    """Short text report: counts plus every flag that blocks."""
    lines = []
    lines.append("Rename rows: %d" % len(tables["rename_table"]))
    flagged = [r for r in tables["rename_table"] if r["flags"]]
    lines.append("Rows with flags: %d" % len(flagged))
    for row in flagged:
        lines.append("  %s -> %s [%s]" % (
            row["old"], row["new"], ", ".join(row["flags"])))
    lines.append("Filters that use an old name: %d"
                 % len(tables["filter_refs"]))
    for hit in tables["filter_refs"]:
        lines.append("  %s (%s) uses %s" % (
            hit["filter_name"], hit["filter_kind"], hit["old_name"]))
    lines.append("Delete flags: %d" % len(tables["delete_flags"]))
    for row in tables["delete_flags"]:
        lines.append("  %s [%s]" % (
            row["name"], ", ".join(row["flags"])))
    lines.append("Label plan rows: %d" % len(tables["label_plan"]))
    lines.append("Paren blockers: %d (rename is not done until "
                 "the user decides about these)"
                 % len(tables["paren_blockers"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--read", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    try:
        inventory = unwrap(load_json(a.read))
        rules = load_json(a.rules)
    except (IOError, ValueError) as e:
        print("ERROR: cannot read input: %s" % e)
        return 2
    try:
        tables = build_tables(inventory, rules)
    except (KeyError, TypeError, ValueError) as e:
        print("ERROR: bad input: %s" % e)
        return 2
    print(render_text(tables))
    if a.out:
        with io.open(a.out, "w", encoding="utf-8") as f:
            json.dump(tables, f, ensure_ascii=False, indent=2,
                      sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

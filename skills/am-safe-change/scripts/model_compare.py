# -*- coding: utf-8 -*-
"""Model version compare: snapshot and diff tool (issue #183).

Compares two model snapshots taken before/after a milestone, sync, or agent run.
Identifies added, deleted, modified (parameter differences), and moved elements.
Compatible with Python 2.7 and 3.x (no f-strings, ASCII only).
"""

import json
import os
import sys


def normalize_snapshot(snap_data):
    """Normalize snapshot data into a dict of {id_str: element_dict}."""
    if isinstance(snap_data, dict) and "elements" in snap_data:
        raw_elems = snap_data["elements"]
    elif isinstance(snap_data, list):
        raw_elems = snap_data
    elif isinstance(snap_data, dict):
        raw_elems = snap_data
    else:
        raw_elems = []

    normalized = {}
    if isinstance(raw_elems, list):
        for el in raw_elems:
            eid = str(el.get("id"))
            if eid and eid != "None":
                normalized[eid] = el
    elif isinstance(raw_elems, dict):
        for k, v in raw_elems.items():
            normalized[str(k)] = v
    return normalized


def compare_snapshots(snap_before, snap_after):
    """Compare two normalized snapshots.

    Returns:
    {
        "summary": {"added": n, "deleted": n, "modified": n, "moved": n, "total_changes": n},
        "added": [elements],
        "deleted": [elements],
        "modified": [{id, category, parameter, old_value, new_value}],
        "moved": [{id, category, old_location, new_location}],
    }
    """
    before_map = normalize_snapshot(snap_before)
    after_map = normalize_snapshot(snap_after)

    before_ids = set(before_map.keys())
    after_ids = set(after_map.keys())

    added_ids = sorted(list(after_ids - before_ids), key=lambda x: str(x))
    deleted_ids = sorted(list(before_ids - after_ids), key=lambda x: str(x))
    common_ids = sorted(list(before_ids & after_ids), key=lambda x: str(x))

    added = [after_map[eid] for eid in added_ids]
    deleted = [before_map[eid] for eid in deleted_ids]

    modified = []
    moved = []

    for eid in common_ids:
        b_el = before_map[eid]
        a_el = after_map[eid]
        cat = a_el.get("category") or b_el.get("category") or "Unknown"

        # Check location
        b_loc = str(b_el.get("location", "")).strip()
        a_loc = str(a_el.get("location", "")).strip()
        if b_loc and a_loc and b_loc != a_loc:
            moved.append({
                "id": eid,
                "category": cat,
                "name": a_el.get("name") or b_el.get("name") or "",
                "old_location": b_loc,
                "new_location": a_loc,
            })

        # Check type or family
        if b_el.get("type") != a_el.get("type"):
            modified.append({
                "id": eid,
                "category": cat,
                "parameter": "Type",
                "old_value": b_el.get("type"),
                "new_value": a_el.get("type"),
            })
        if b_el.get("family") != a_el.get("family"):
            modified.append({
                "id": eid,
                "category": cat,
                "parameter": "Family",
                "old_value": b_el.get("family"),
                "new_value": a_el.get("family"),
            })

        # Check parameters
        b_params = b_el.get("parameters", {}) or {}
        a_params = a_el.get("parameters", {}) or {}
        all_param_keys = sorted(list(set(b_params.keys()) | set(a_params.keys())))

        for p in all_param_keys:
            v_b = b_params.get(p)
            v_a = a_params.get(p)
            if v_b != v_a:
                modified.append({
                    "id": eid,
                    "category": cat,
                    "parameter": p,
                    "old_value": v_b,
                    "new_value": v_a,
                })

    total_changes = len(added) + len(deleted) + len(modified) + len(moved)
    return {
        "summary": {
            "added": len(added),
            "deleted": len(deleted),
            "modified": len(modified),
            "moved": len(moved),
            "total_changes": total_changes,
        },
        "added": added,
        "deleted": deleted,
        "modified": modified,
        "moved": moved,
    }


def format_report_markdown(comparison):
    """Format comparison result as a readable Markdown report."""
    s = comparison["summary"]
    lines = [
        "# Model Version Compare Report",
        "",
        "## Summary",
        "- **Added elements**: %d" % s["added"],
        "- **Deleted elements**: %d" % s["deleted"],
        "- **Modified properties**: %d" % s["modified"],
        "- **Moved elements**: %d" % s["moved"],
        "- **Total changes**: %d" % s["total_changes"],
        "",
    ]

    if comparison["added"]:
        lines.append("## Added Elements (%d)" % len(comparison["added"]))
        lines.append("| ID | Category | Name |")
        lines.append("|---|---|---|")
        for el in comparison["added"][:50]:
            lines.append("| %s | %s | %s |" % (
                el.get("id"), el.get("category", ""), el.get("name", "")
            ))
        if len(comparison["added"]) > 50:
            lines.append("| ... | and %d more | |" % (len(comparison["added"]) - 50))
        lines.append("")

    if comparison["deleted"]:
        lines.append("## Deleted Elements (%d)" % len(comparison["deleted"]))
        lines.append("| ID | Category | Name |")
        lines.append("|---|---|---|")
        for el in comparison["deleted"][:50]:
            lines.append("| %s | %s | %s |" % (
                el.get("id"), el.get("category", ""), el.get("name", "")
            ))
        if len(comparison["deleted"]) > 50:
            lines.append("| ... | and %d more | |" % (len(comparison["deleted"]) - 50))
        lines.append("")

    if comparison["modified"]:
        lines.append("## Modified Properties (%d)" % len(comparison["modified"]))
        lines.append("| ID | Category | Parameter | Old Value | New Value |")
        lines.append("|---|---|---|---|---|")
        for m in comparison["modified"][:50]:
            lines.append("| %s | %s | %s | %s | %s |" % (
                m["id"], m["category"], m["parameter"], m["old_value"], m["new_value"]
            ))
        if len(comparison["modified"]) > 50:
            lines.append("| ... | and %d more | | | |" % (len(comparison["modified"]) - 50))
        lines.append("")

    if comparison["moved"]:
        lines.append("## Moved Elements (%d)" % len(comparison["moved"]))
        lines.append("| ID | Category | Old Location | New Location |")
        lines.append("|---|---|---|---|")
        for mv in comparison["moved"][:50]:
            lines.append("| %s | %s | %s | %s |" % (
                mv["id"], mv["category"], mv["old_location"], mv["new_location"]
            ))
        if len(comparison["moved"]) > 50:
            lines.append("| ... | and %d more | | |" % (len(comparison["moved"]) - 50))
        lines.append("")

    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if len(args) < 2 or args[0] in ("-h", "--help"):
        print("Usage: model_compare.py <before.json> <after.json> [--out <report.md>] [--json]")
        return 0

    before_path = args[0]
    after_path = args[1]
    out_path = None
    as_json = "--json" in args

    for i, a in enumerate(args):
        if a == "--out" and i + 1 < len(args):
            out_path = args[i + 1]

    with open(before_path, "r") as f:
        snap_b = json.load(f)
    with open(after_path, "r") as f:
        snap_a = json.load(f)

    diff = compare_snapshots(snap_b, snap_a)

    if as_json:
        output_text = json.dumps(diff, indent=2)
    else:
        output_text = format_report_markdown(diff)

    if out_path:
        with open(out_path, "w") as f:
            f.write(output_text)
        print("Wrote compare report to %s" % out_path)
    else:
        print(output_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

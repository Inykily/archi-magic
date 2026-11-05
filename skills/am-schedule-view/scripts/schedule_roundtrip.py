# -*- coding: utf-8 -*-
"""Excel / CSV round trip for Revit schedules with safe write-back (issue #128).

Exports schedule data with element IDs to spreadsheet-compatible CSV, validates
re-imported changes, blocks edits to read-only or calculated fields, and generates
am-safe-change preview JSON.
Compatible with Python 2.7 and 3.x (no f-strings, ASCII only).
"""

import csv
import json
import os
import sys

DEFAULT_READ_ONLY_FIELDS = set([
    "id",
    "element_id",
    "area",
    "volume",
    "level",
    "count",
    "family",
    "category",
    "calculated",
    "perimeter",
    "phase created",
    "phase demolished",
])


def is_read_only_field(field_name, custom_read_only=None):
    """Check if a field name is considered read-only/calculated."""
    fn = field_name.strip().lower()
    if custom_read_only:
        for cro in custom_read_only:
            if cro.strip().lower() == fn:
                return True
    return fn in DEFAULT_READ_ONLY_FIELDS


def export_schedule_csv(schedule_data, out_csv_path):
    """Export schedule rows to a spreadsheet CSV with element ID as first column."""
    columns = schedule_data.get("columns", [])
    if "Element ID" not in columns:
        columns = ["Element ID"] + columns

    rows = schedule_data.get("rows", [])
    dir_name = os.path.dirname(out_csv_path)
    if dir_name and not os.path.exists(dir_name):
        try:
            os.makedirs(dir_name)
        except Exception:
            pass

    with open(out_csv_path, "w") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for r in rows:
            row_vals = []
            for col in columns:
                if col == "Element ID":
                    val = r.get("id") or r.get("element_id") or ""
                else:
                    val = r.get(col, "")
                row_vals.append(val)
            writer.writerow(row_vals)


def parse_imported_csv(csv_path):
    """Parse edited CSV into a list of row dicts."""
    rows = []
    with open(csv_path, "r") as f:
        reader = csv.reader(f)
        headers = []
        for row in reader:
            if not headers:
                headers = [h.strip() for h in row]
                continue
            if not row or not any(row):
                continue
            r_dict = {}
            for i, h in enumerate(headers):
                val = row[i] if i < len(row) else ""
                r_dict[h] = val
            rows.append(r_dict)
    return headers, rows


def diff_schedule_import(original_rows, edited_rows, custom_read_only=None):
    """Compare original schedule rows with edited rows and generate safe-change preview."""
    orig_map = {}
    for r in original_rows:
        eid = str(r.get("id") or r.get("Element ID") or r.get("element_id") or "")
        if eid:
            orig_map[eid] = r

    changed_cells = []
    warnings = []
    unchanged_count = 0

    for e_row in edited_rows:
        eid = str(e_row.get("id") or e_row.get("Element ID") or e_row.get("element_id") or "")
        if not eid or eid not in orig_map:
            continue
        orig = orig_map[eid]

        for col, new_val in e_row.items():
            if col in ("id", "Element ID", "element_id"):
                continue
            old_val = orig.get(col, "")
            # String comparison of values
            if str(new_val).strip() != str(old_val).strip():
                is_ro = is_read_only_field(col, custom_read_only)
                cell_diff = {
                    "element_id": eid,
                    "field": col,
                    "old_value": str(old_val),
                    "new_value": str(new_val),
                    "read_only": is_ro,
                }
                changed_cells.append(cell_diff)
                if is_ro:
                    warnings.append({
                        "kind": "blocking",
                        "row": eid,
                        "field": col,
                        "message": "Field '%s' is read-only or calculated in Revit. Cannot write back." % col,
                    })
            else:
                unchanged_count += 1

    has_blocking = any(w.get("kind") == "blocking" for w in warnings)

    # Preview rows
    preview_rows = []
    for c in changed_cells:
        preview_rows.append({
            "Element ID": c["element_id"],
            "Field": c["field"],
            "Before": c["old_value"],
            "After": c["new_value"],
        })

    return {
        "recipe": "schedule_excel_roundtrip",
        "columns": ["Element ID", "Field", "Before", "After"],
        "rows": preview_rows,
        "counts": {
            "changed": len(changed_cells),
            "unchanged": unchanged_count,
            "warnings": len(warnings),
        },
        "warnings": warnings,
        "blocked": has_blocking,
    }


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: schedule_roundtrip.py <export|preview> [options]")
        return 0

    cmd = args[0]

    if cmd == "export":
        data_file = None
        out_csv = None
        i = 1
        while i < len(args):
            if args[i] == "--schedule" and i + 1 < len(args):
                data_file = args[i + 1]
                i += 2
            elif args[i] == "--out" and i + 1 < len(args):
                out_csv = args[i + 1]
                i += 2
            else:
                i += 1

        if not data_file or not out_csv:
            print("Error: --schedule and --out required")
            return 1

        with open(data_file, "r") as f:
            sched = json.load(f)
        export_schedule_csv(sched, out_csv)
        print("Exported schedule to %s" % out_csv)
        return 0

    elif cmd == "preview":
        orig_file = None
        edited_csv = None
        out_file = None
        i = 1
        while i < len(args):
            if args[i] == "--original" and i + 1 < len(args):
                orig_file = args[i + 1]
                i += 2
            elif args[i] == "--edited" and i + 1 < len(args):
                edited_csv = args[i + 1]
                i += 2
            elif args[i] == "--out" and i + 1 < len(args):
                out_file = args[i + 1]
                i += 2
            else:
                i += 1

        if not orig_file or not edited_csv:
            print("Error: --original and --edited required")
            return 1

        with open(orig_file, "r") as f:
            orig = json.load(f)
            if isinstance(orig, dict) and "rows" in orig:
                orig_rows = orig["rows"]
            else:
                orig_rows = orig

        _, edited_rows = parse_imported_csv(edited_csv)
        preview = diff_schedule_import(orig_rows, edited_rows)
        out_str = json.dumps(preview, indent=2)

        if out_file:
            with open(out_file, "w") as f:
                f.write(out_str)
            print("Wrote preview to %s (blocked=%s)" % (out_file, preview["blocked"]))
        else:
            print(out_str)
        return 0

    else:
        print("Unknown command: %s" % cmd)
        return 1


if __name__ == "__main__":
    sys.exit(main())

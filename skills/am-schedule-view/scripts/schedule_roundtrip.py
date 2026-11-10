# -*- coding: utf-8 -*-
"""Excel / CSV round trip for Revit schedules with safe write-back (issue #128).

Exports schedule data with element IDs to spreadsheet-compatible CSV, validates
re-imported changes, blocks edits to read-only or calculated fields, and generates
am-safe-change preview JSON.
The legacy workflow supports Python 2.7 and 3.x. The grid requires Python 3.8+.
"""

from __future__ import print_function

import argparse
import csv
import hashlib
import io
import json
import os
import re
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


SNAPSHOT_KIND = "parameter-grid-snapshot"
PACKET_KIND = "schedule-grid-edits"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500
MAX_FIELDS = 20
MAX_VALUE_LENGTH = 2000
ID_HEADERS = {"id", "element_id", "element id", "elementid"}


def read_bytes(path):
    with open(path, "rb") as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Input exceeds 2 MiB.")
    return data


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: %s" % key)
        result[key] = value
    return result


def strict_json(data):
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique_keys)


def normalize_value(value):
    if not isinstance(value, str) or len(value) > MAX_VALUE_LENGTH or "\x00" in value:
        raise ValueError("Cells must be text of at most 2,000 characters, without NUL.")
    # Reject escaped lone surrogates, which cannot round-trip through UTF-8 CSV.
    value.encode("utf-8")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def validated_snapshot(data):
    if not isinstance(data, dict) or data.get("kind") != SNAPSHOT_KIND:
        raise ValueError("Use an identity-bearing parameter-grid-snapshot.")
    if set(data) - {"kind", "columns", "rows", "read_only_fields"}:
        raise ValueError("Unexpected snapshot keys.")
    fields = data.get("columns")
    if not isinstance(fields, list) or not 1 <= len(fields) <= MAX_FIELDS:
        raise ValueError("Select 1 to 20 parameter fields.")
    for field in fields:
        if (not isinstance(field, str) or not 1 <= len(field) <= 120
                or field != field.strip() or field.lower() in ID_HEADERS
                or any(ord(char) < 32 for char in field)):
            raise ValueError("Invalid parameter field name.")
        field.encode("utf-8")
    if len({field.lower() for field in fields}) != len(fields):
        raise ValueError("Parameter field names must be distinct.")

    read_only = data.get("read_only_fields", [])
    if not isinstance(read_only, list) or any(field not in fields for field in read_only):
        raise ValueError("Read-only fields must be selected parameter fields.")

    rows = data.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("Select 1 to 500 elements.")
    expected_keys = set(fields) | {"id"}
    normalized = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_keys:
            raise ValueError("Each element needs an ID and exactly the selected fields.")
        eid = row["id"]
        if (not isinstance(eid, str) or not re.fullmatch("[1-9][0-9]{0,18}", eid)
                or int(eid) > 2 ** 63 - 1 or eid in normalized):
            raise ValueError("Element IDs must be unique positive 64-bit decimal strings.")
        normalized[eid] = {field: normalize_value(row[field]) for field in fields}
    return fields, normalized, [field for field in fields if is_read_only_field(field, read_only)]


def grid_edits(data, digest, fields, rows):
    packet = strict_json(data)
    if (not isinstance(packet, dict) or set(packet) != {"kind", "snapshot_sha256", "edits"}
            or packet["kind"] != PACKET_KIND or packet["snapshot_sha256"] != digest):
        raise ValueError("The edit packet must match the original snapshot file.")
    items = packet["edits"]
    if not isinstance(items, list) or len(items) > len(fields) * len(rows):
        raise ValueError("Invalid grid edit list.")
    edits = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "field", "value"}:
            raise ValueError("Each edit needs an ID, field and value.")
        eid, field = item["id"], item["field"]
        if not isinstance(eid, str) or eid not in rows or not isinstance(field, str) or field not in fields:
            raise ValueError("Unknown element ID or field.")
        if (eid, field) in edits:
            raise ValueError("Duplicate grid edit.")
        edits[eid, field] = normalize_value(item["value"])
    return edits


def csv_edits(data, fields, rows):
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    headers = next(reader, [])
    if headers != ["Element ID"] + fields:
        raise ValueError("Use the exported Element ID and parameter headers in order.")
    edits, seen = {}, set()
    for values in reader:
        if not values:
            continue
        eid = values[0]
        if len(values) != len(headers) or eid not in rows or eid in seen:
            raise ValueError("CSV rows need a known, unique ID and one value per field.")
        seen.add(eid)
        for field, value in zip(fields, values[1:]):
            edits[eid, field] = normalize_value(value)
    return edits


def standard_preview(fields, rows, read_only, edits):
    original = [dict(values, id=eid) for eid, values in rows.items()]
    proposed = [
        dict({field: edits.get((eid, field), values[field]) for field in fields}, id=eid)
        for eid, values in rows.items()
    ]
    preview = diff_schedule_import(original, proposed, read_only)
    changes = {(cell["Element ID"], cell["Field"]): cell["After"] for cell in preview["rows"]}
    changed_fields = {field for _, field in changes}
    changed_ids = {eid for eid, _ in changes}
    for warning in preview["warnings"]:
        warning.update(text=warning["message"], blocking=True)
    preview.update(
        kind="change-preview",
        title="Schedule parameter changes",
        keyColumn="Element ID",
        legacy_columns=preview["columns"],
        columns=["Element ID"] + fields,
        changedColumns=[field for field in fields if field in changed_fields],
        before=[[eid] + list(values.values()) for eid, values in rows.items()],
        after=[
            [eid] + [changes.get((eid, field), values[field]) for field in fields]
            for eid, values in rows.items()
        ],
        notes=["Review only. Use an explicit safe-change recipe and Revit preflight for any model write."],
        ownership_ids=[eid for eid in rows if eid in changed_ids],
        steps=[],
        review_only=True,
    )
    return preview


def write_grid(path, fields, rows, read_only, digest):
    template_path = os.path.join(os.path.dirname(__file__), "..", "assets", "parameter-grid.html")
    payload = json.dumps({
        "fields": fields, "rows": list(rows.items()), "readOnly": read_only,
        "snapshotSha256": digest, "maxBytes": MAX_BYTES, "maxValueLength": MAX_VALUE_LENGTH,
    }, ensure_ascii=True).replace("<", "\\u003c")
    with io.open(template_path, encoding="utf-8") as source:
        page = source.read().replace("__GRID_DATA__", payload)
    with io.open(path, "w", encoding="utf-8") as output:
        output.write(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    for name in ("export", "grid"):
        command = commands.add_parser(name)
        command.add_argument("--schedule", required=True)
        command.add_argument("--out", required=True)
    for name in ("preview", "preview-grid"):
        command = commands.add_parser(name)
        command.add_argument("--original", required=True)
        command.add_argument("--edited", required=True)
        command.add_argument("--out")
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return run(args)
    except (IOError, OSError, ValueError, csv.Error, RuntimeError) as error:
        print("Error: %s" % error, file=sys.stderr)
        return 1


def run(args):
    data = read_bytes(getattr(args, "schedule", None) or args.original)
    snapshot = strict_json(data)
    marked = isinstance(snapshot, dict) and snapshot.get("kind") == SNAPSHOT_KIND
    if args.command in ("grid", "preview-grid") or marked:
        if sys.version_info < (3, 8):
            raise ValueError("The parameter grid requires Python 3.8 or newer.")
        fields, rows, read_only = validated_snapshot(snapshot)
        digest = hashlib.sha256(data).hexdigest()
        if args.command == "grid":
            write_grid(args.out, fields, rows, read_only, digest)
            return 0
        if args.command == "export":
            with io.open(args.out, "w", encoding="utf-8", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(["Element ID"] + fields)
                writer.writerows([eid] + list(values.values()) for eid, values in rows.items())
            return 0
        edited = read_bytes(args.edited)
        edits = (grid_edits(edited, digest, fields, rows) if args.command == "preview-grid"
                 else csv_edits(edited, fields, rows))
        preview = standard_preview(fields, rows, read_only, edits)
    elif args.command == "export":
        export_schedule_csv(snapshot, args.out)
        print("Exported schedule to %s" % args.out)
        return 0
    else:
        original = snapshot["rows"] if isinstance(snapshot, dict) and "rows" in snapshot else snapshot
        _, edited_rows = parse_imported_csv(args.edited)
        preview = diff_schedule_import(original, edited_rows)

    rendered = json.dumps(preview, indent=2)
    if args.out:
        with open(args.out, "w") as output:
            output.write(rendered)
        print("Wrote preview to %s (blocked=%s)" % (args.out, preview["blocked"]))
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Merge batched material quantity reads into one takeoff report and check scope coverage.

Inputs are saved run_query responses (or their decoded payloads):
  --scope      the result of read_takeoff_scope.py
  --query      one result of am-material-audit/scripts/read_material_quantities.py per batch
               (repeat it), or --query-dir with one JSON file per batch
  --recheck    optional second read of the same scope, made after the last batch
  --csv        optional output: material,category,level,area_m2,volume_m3 (complete reports only)

Exit 0: complete (or complete with notes). Exit 1: incomplete evidence. Exit 2: invalid input.
"""
from __future__ import print_function

import argparse
from decimal import Decimal, DecimalException, localcontext
import hashlib
import io
import json
import os
import re
import sys

try:
    TEXT = basestring  # noqa: F821 (IronPython 2.7)
    WHOLE = (int, long)  # noqa: F821
except NameError:
    TEXT = str
    WHOLE = (int,)

MAX_INPUT = 8 * 1024 * 1024
MAX_QUERIES = 400
MAX_BATCH = 500
MAX_ROWS = 5000
NOTE_REASONS = ("no_geometry_materials", "level_unknown")
NO_LEVEL = "(no level)"
OK_STATUS = ("ok", "success", "succeeded", "completed")
CHANGE_COUNTS = ("added_count", "modified_count", "deleted_count")
CHANGE_LISTS = ("added", "modified", "deleted", "added_ids", "modified_ids", "deleted_ids",
                "by_category", "other_documents")
RUNTIME_FLAGS = ("failures", "blocked", "warnings", "dialogs", "closed_documents", "unclosed_documents")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
DECIMAL_ID = re.compile(r"[1-9][0-9]{0,18}\Z")
ZERO = Decimal(0)
LIMIT = Decimal("1e18")


class Incomplete(ValueError):
    """The evidence is valid but does not support a complete report."""

    def __init__(self, message, issues=()):
        ValueError.__init__(self, message)
        self.issues = list(issues)


def unique_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("duplicate JSON field " + key)
        fields[key] = value
    return fields


def parse_json(text):
    return json.loads(text, parse_float=Decimal, object_pairs_hook=unique_fields)


def read_file(path):
    with io.open(path, "rb") as stream:
        data = stream.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        raise ValueError(path + ": input exceeds 8 MiB")
    return parse_json(data.decode("utf-8-sig"))


def whole(value):
    return isinstance(value, WHOLE) and not isinstance(value, bool)


def decimal_ids(values, label):
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_BATCH:
        raise ValueError(label + ": expected 1 to 500 element IDs")
    for value in values:
        if not isinstance(value, TEXT) or not DECIMAL_ID.match(value) or int(value) >= 2 ** 63:
            raise ValueError(label + ": invalid element ID")
    if len(set(values)) != len(values):
        raise ValueError(label + ": an element ID is repeated")
    return frozenset(values)


def unwrap(record, label):
    """Return the decoded report from a saved runtime response, a result, or a payload."""
    if not isinstance(record, dict):
        raise ValueError(label + ": expected a JSON object")
    if "response" in record:
        record = record["response"]
        if not isinstance(record, dict):
            raise ValueError(label + ": expected a saved runtime response")
    if set(("result", "mode", "run_id", "result_truncated", "changes")) & set(record):
        exit_code = record.get("exit_code", 0)
        if (record.get("status", "ok") not in OK_STATUS or not whole(exit_code) or exit_code != 0
                or record.get("error") or record.get("mode", "query") != "query"
                or record.get("result_truncated", False) is not False
                or any(record.get(key) for key in RUNTIME_FLAGS)):
            raise Incomplete(label + ": save the complete, successful read-only query response "
                             "(use get_run when the response is truncated)")
        if set(("changes", "mode", "run_id")) & set(record):
            changes = record.get("changes")
            if (not isinstance(changes, dict)
                    or any(not whole(changes.get(key)) or changes[key] != 0 for key in CHANGE_COUNTS)
                    or any(changes.get(key) for key in CHANGE_LISTS)):
                raise Incomplete(label + ": the saved response does not show zero model changes")
        record = record.get("result")
    if not isinstance(record, dict):
        raise Incomplete(label + ": the query returned no result")
    if record.get("error"):
        raise Incomplete(label + ": the query returned an error: " + str(record.get("error")))
    if "payload" in record:
        if not isinstance(record["payload"], TEXT):
            raise ValueError(label + ": the payload is not text")
        record = parse_json(record["payload"])
    if not isinstance(record, dict):
        raise ValueError(label + ": expected a decoded report object")
    return record


def project_of(report, label):
    stamp = report.get("project")
    if (not isinstance(stamp, dict) or not isinstance(stamp.get("uid"), TEXT) or not stamp["uid"]
            or not isinstance(stamp.get("path_sha256"), TEXT) or not HEX64.match(stamp["path_sha256"])):
        raise Incomplete(label + ": read a saved project (the report has no project stamp)")
    return stamp["uid"], stamp["path_sha256"]


def name_table(entries, label, allow_none):
    names = {}
    for entry in entries if isinstance(entries, list) else [None]:
        if not isinstance(entry, dict) or not whole(entry.get("id")) or entry["id"] in names:
            raise ValueError(label + ": invalid or repeated name entry")
        name = entry.get("name")
        if not (isinstance(name, TEXT) and name.strip()) and not (allow_none and name is None
                                                                  and entry["id"] == -1):
            raise ValueError(label + ": an entry has no name")
        names[entry["id"]] = NO_LEVEL if name is None else name.strip()
    return names


def read_scope(report, label="scope"):
    if report.get("kind") != "takeoff-scope":
        raise ValueError(label + ": expected the result of read_takeoff_scope.py")
    if report.get("status") != "ready":
        raise Incomplete(label + ": the scope read is not ready. Fix its issues, or narrow the scope, "
                         "and read it again", report.get("issues") or [])
    project = project_of(report, label)
    batches = report.get("batches")
    if not isinstance(batches, list) or not 1 <= len(batches) <= MAX_QUERIES:
        raise ValueError(label + ": expected 1 to 400 batches")
    seen = set()
    plan = []
    for position, batch in enumerate(batches, 1):
        if not isinstance(batch, dict) or batch.get("index") != position:
            raise ValueError(label + ": batch numbers must run 1, 2, 3 and so on")
        ids = decimal_ids(batch.get("element_ids"), label + " batch " + str(position))
        if seen & ids:
            raise ValueError(label + ": an element ID is in two batches")
        seen.update(ids)
        groups = batch.get("groups")
        if not isinstance(groups, list) or not groups:
            raise ValueError(label + ": batch " + str(position) + " has no category and level groups")
        pairs = set()
        for pair in groups:
            if not isinstance(pair, list) or len(pair) != 2 or not all(whole(value) for value in pair):
                raise ValueError(label + ": invalid category and level group")
            pairs.add((pair[0], pair[1]))
        plan.append({"index": position, "ids": ids, "count": len(ids), "groups": pairs})
    joined = ",".join(value for batch in batches for value in batch["element_ids"])
    digest = hashlib.sha256(joined.encode("ascii")).hexdigest()
    if report.get("scope_sha256") != digest:
        raise ValueError(label + ": the scope digest does not match the batches")
    if report.get("element_count") != len(seen):
        raise ValueError(label + ": the element count does not match the batches")
    categories = name_table(report.get("categories"), label, False)
    levels = name_table(report.get("levels"), label, True)
    counts = {}
    for group in report.get("groups") if isinstance(report.get("groups"), list) else [None]:
        if (not isinstance(group, dict) or group.get("category_id") not in categories
                or group.get("level_id") not in levels or not whole(group.get("elements"))
                or group["elements"] < 1):
            raise ValueError(label + ": invalid group summary")
        counts[(group["category_id"], group["level_id"])] = group["elements"]
    if sum(counts.values()) != len(seen) or set().union(*[b["groups"] for b in plan]) != set(counts):
        raise ValueError(label + ": the group summary does not match the batches")
    return {"project": project, "batches": plan, "digest": digest, "element_count": len(seen),
            "categories": categories, "levels": levels, "group_counts": counts,
            "request": report.get("request"), "excluded": report.get("excluded")}


def quantity(value, label, field):
    if whole(value):
        value = Decimal(value)
    if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO or value >= LIMIT:
        raise ValueError(label + ": invalid " + field)
    return value


def read_quantity(report, label):
    ids = report.get("requested_element_ids")
    if not isinstance(ids, list) or report.get("requested_elements") != len(ids):
        raise Incomplete(label + ": rerun read_material_quantities.py so that it records its element IDs")
    ids = decimal_ids(ids, label)
    project = project_of(report, label)
    status, issues = report.get("status"), report.get("issues")
    if (status not in ("reported", "incomplete") or not isinstance(issues, list)
            or (status == "reported") != (not issues)):
        raise ValueError(label + ": the status and the issue list do not agree")
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError(label + ": expected up to 5,000 quantity rows")
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(label + ": invalid quantity row")
        category_id, level_id, material_id = row.get("category_id"), row.get("level_id"), row.get("material_id")
        if (not all(whole(value) for value in (category_id, level_id, material_id)) or category_id == 0
                or material_id <= 0 or not (level_id == -1 or level_id > 0)):
            raise ValueError(label + ": a quantity row has an invalid ID")
        names = [row.get("category"), row.get("material")]
        level = row.get("level")
        if level_id != -1:
            names.append(level)
        elif level is not None:
            raise ValueError(label + ": a row without a level has a level name")
        if not all(isinstance(name, TEXT) and name.strip() for name in names):
            raise ValueError(label + ": a quantity row has an empty name")
        parsed.append({"category_id": category_id, "level_id": level_id, "material_id": material_id,
                       "category": row["category"].strip(), "material": row["material"].strip(),
                       "level": NO_LEVEL if level_id == -1 else level.strip(),
                       "area_m2": quantity(row.get("area_m2"), label, "area_m2"),
                       "volume_m3": quantity(row.get("volume_m3"), label, "volume_m3")})
    return {"label": label, "project": project, "ids": ids, "rows": parsed, "issues": issues}


def recheck(scope, again):
    if (again["project"] != scope["project"] or again["digest"] != scope["digest"]
            or again["group_counts"] != scope["group_counts"]
            or [batch["ids"] for batch in again["batches"]] != [batch["ids"] for batch in scope["batches"]]):
        raise Incomplete("the scope changed between the first and the second scope read. "
                         "Read the scope and every batch again")


def check_name(names, field, identifier, name):
    if names.setdefault((field, "id", identifier), name) != name:
        raise ValueError("one " + field + " ID has two names: " + name)
    if names.setdefault((field, "name", name), identifier) != identifier:
        raise ValueError("two " + field + " IDs have the same name: " + name)


def add(table, key, area, volume):
    total = table.setdefault(key, [ZERO, ZERO])
    total[0] += area
    total[1] += volume


def decimal_text(value):
    return format(value, "f")


def merge(scope, queries):
    by_ids = dict((batch["ids"], batch) for batch in scope["batches"])
    received = {}
    for query in queries:
        if query["project"] != scope["project"]:
            raise ValueError(query["label"] + ": comes from a different saved project than the scope")
        batch = by_ids.get(query["ids"])
        if batch is None:
            raise ValueError(query["label"] + ": its element IDs are not equal to one scope batch. "
                             "Run the quantity read with the exact element_ids of one batch")
        if batch["index"] in received:
            raise ValueError(query["label"] + ": batch " + str(batch["index"]) + " is given twice")
        received[batch["index"]] = query

    issues, notes, names, groups = [], {}, {}, {}
    for batch in scope["batches"]:
        query = received.get(batch["index"])
        if query is None:
            issues.append({"batch": batch["index"], "reason": "batch_missing", "elements": batch["count"]})
            continue
        for issue in query["issues"]:
            reason = issue.get("reason") if isinstance(issue, dict) else None
            if reason in NOTE_REASONS:
                note = notes.setdefault(reason, {"reason": reason, "count": 0, "element_ids": []})
                note["count"] += 1
                if "element_id" in issue and len(note["element_ids"]) < 50:
                    note["element_ids"].append(str(issue["element_id"]))
            else:
                entry = dict(issue) if isinstance(issue, dict) else {"reason": "unreadable_issue"}
                entry["batch"] = batch["index"]
                issues.append(entry)
        for row in query["rows"]:
            if (row["category_id"], row["level_id"]) not in batch["groups"]:
                issues.append({"batch": batch["index"], "reason": "row_outside_scope_group",
                               "category": row["category"], "level": row["level"]})
            elif (scope["categories"][row["category_id"]] != row["category"]
                  or scope["levels"][row["level_id"]] != row["level"]):
                issues.append({"batch": batch["index"], "reason": "name_changed_after_scope_read",
                               "category": row["category"], "level": row["level"]})
            for field in ("category", "level", "material"):
                check_name(names, field, row[field + "_id"], row[field])
            key = (row["category"], row["level"], row["material"])
            add(groups, key, row["area_m2"], row["volume_m3"])

    by_category, by_level, by_material, total = {}, {}, {}, [ZERO, ZERO]
    for (category, level, material), (area, volume) in groups.items():
        add(by_category, category, area, volume)
        add(by_level, level, area, volume)
        add(by_material, material, area, volume)
        total[0] += area
        total[1] += volume
    category_elements, level_elements = {}, {}
    for (category_id, level_id), count in scope["group_counts"].items():
        category = scope["categories"][category_id]
        level = scope["levels"][level_id]
        category_elements[category] = category_elements.get(category, 0) + count
        level_elements[level] = level_elements.get(level, 0) + count

    def rollup(table, elements, field):
        rows = []
        for key in sorted(set(table) | set(elements or {})):
            area, volume = table.get(key, [ZERO, ZERO])
            row = {field: key, "area_m2": decimal_text(area), "volume_m3": decimal_text(volume)}
            if elements is not None:
                row["elements"] = elements.get(key, 0)
            rows.append(row)
        return rows

    status = "incomplete" if issues else ("complete_with_notes" if notes else "complete")
    received_elements = sum(batch["count"] for batch in scope["batches"] if batch["index"] in received)
    return {
        "kind": "takeoff-report",
        "status": status,
        "scope": {"request": scope["request"], "excluded": scope["excluded"],
                  "scope_sha256": scope["digest"], "elements": scope["element_count"]},
        "coverage": {"batches_expected": len(scope["batches"]), "batches_received": len(received),
                     "elements_expected": scope["element_count"], "elements_received": received_elements},
        "rows": [{"material": material, "category": category, "level": level,
                  "area_m2": decimal_text(area), "volume_m3": decimal_text(volume)}
                 for (category, level, material), (area, volume) in sorted(groups.items())],
        "by_category": rollup(by_category, category_elements, "category"),
        "by_level": rollup(by_level, level_elements, "level"),
        "by_material": rollup(by_material, None, "material"),
        "total": {"area_m2": decimal_text(total[0]), "volume_m3": decimal_text(total[1])},
        "notes": [notes[key] for key in sorted(notes)],
        "issues": issues,
        "limits": "Host-model geometry and compound layers of the listed elements only. "
                  "No linked models and no paint. Material area is the sum over all materials.",
    }


def csv_field(value):
    value = value if isinstance(value, TEXT) else str(value)
    if any(character in value for character in ",\"\r\n"):
        value = "\"" + value.replace("\"", "\"\"") + "\""
    return value


def write_csv(path, rows):
    lines = [u"material,category,level,area_m2,volume_m3"]
    for row in rows:
        lines.append(u",".join(csv_field(row[field]) for field in
                               ("material", "category", "level", "area_m2", "volume_m3")))
    with io.open(path, "w", encoding="utf-8", newline="") as stream:
        stream.write(u"\r\n".join(lines) + u"\r\n")


def query_paths(args):
    paths = list(args.query)
    if args.query_dir:
        skip = set(os.path.normcase(os.path.abspath(path)) for path in (args.scope, args.recheck) if path)
        for name in sorted(os.listdir(args.query_dir)):
            path = os.path.join(args.query_dir, name)
            if name.lower().endswith(".json") and os.path.normcase(os.path.abspath(path)) not in skip:
                paths.append(path)
    if not paths:
        raise ValueError("give --query or --query-dir")
    if len(paths) > MAX_QUERIES:
        raise ValueError("give up to 400 query files")
    if len(set(os.path.normcase(os.path.abspath(path)) for path in paths)) != len(paths):
        raise ValueError("a query file is given twice")
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", required=True)
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--query-dir")
    parser.add_argument("--recheck")
    parser.add_argument("--csv")
    args = parser.parse_args(argv)
    try:
        with localcontext() as context:
            context.prec = 60
            scope = read_scope(unwrap(read_file(args.scope), "scope"))
            if args.recheck:
                recheck(scope, read_scope(unwrap(read_file(args.recheck), "recheck"), "recheck"))
            queries = []
            for path in query_paths(args):
                label = os.path.basename(path)
                queries.append(read_quantity(unwrap(read_file(path), label), label))
            report = merge(scope, queries)
        if args.csv and report["status"] != "incomplete":
            write_csv(args.csv, report["rows"])
            report["csv"] = args.csv
        elif args.csv:
            report["csv"] = None
            report["csv_skipped"] = "The report is incomplete. No CSV was written."
    except Incomplete as exc:
        print(json.dumps({"status": "incomplete", "reason": str(exc), "issues": exc.issues},
                         indent=2, default=str))
        return 1
    except (IOError, OSError, ValueError, TypeError, KeyError, DecimalException) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=True, default=str))
    return 1 if report["status"] == "incomplete" else 0


if __name__ == "__main__":
    sys.exit(main())

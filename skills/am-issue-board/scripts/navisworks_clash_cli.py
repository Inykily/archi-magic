"""Preview Navisworks clash intake and optional Revit section bounds."""

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import uuid
import xml.etree.ElementTree as ET

import bcf_cli
import board_cli
import issue_board as ib

LIMIT = 2 * 1024 * 1024
MARKER = "Navisworks clash UUID: "
STATUSES = {"new", "active", "reviewed", "approved", "resolved"}
FRAME = "revit_host_internal_feet"
RESULT = ("exchange", "batchtest", "clashtests", "clashtest", "clashresults")


def local_bytes(raw):
    windows_drive = os.name == "nt" and re.match(r"^[a-zA-Z]:[/\\]", raw)
    if raw.startswith(("//", "\\")) or ":" in (raw[2:] if windows_drive else raw):
        raise ValueError("Use a regular local input file.")
    path = Path(raw)
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0))
    original = path.lstat()
    if (not stat.S_ISREG(original.st_mode) or getattr(original, "st_file_attributes", 0) & 0x400
            or original.st_size > LIMIT):
        raise ValueError("Use a regular local input file up to 2 MiB.")
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        if not os.path.samestat(original, before) or not stat.S_ISREG(before.st_mode):
            raise ValueError("Input identity changed before reading.")
        data = stream.read(LIMIT + 1)
        after = os.fstat(stream.fileno())
        current = path.lstat()
        if not (len(data) <= LIMIT and len(data) == before.st_size == after.st_size == current.st_size
                and before.st_mtime_ns == after.st_mtime_ns == current.st_mtime_ns
                and os.path.samestat(before, current)):
            raise ValueError("Input changed while reading.")
    return data


def json_input(data):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("Duplicate JSON field.")
            result[name] = value
        return result

    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique)


def text(value):
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("Report text exceeds the supported limit.")
    return value.strip()


def object_side(node):
    candidates = set()
    for attr in node.findall("objectattribute") + node.findall("smarttags/smarttag"):
        if text(attr.findtext("name", "")).casefold() == "element id":
            candidates.add(text(attr.findtext("value", "")))
    item_id = next(iter(candidates)) if len(candidates) == 1 else None
    if item_id and not (
        re.fullmatch(r"[1-9][0-9]{0,18}", item_id) and int(item_id) <= 2**63 - 1
    ):
        item_id = None
    paths = node.findall("pathlink")
    nodes = [text(entry.text or "") for entry in paths[0].findall("node")] if len(paths) == 1 else []
    return {"element_id": item_id, "selection_path": nodes}


def valid_result_path(path):
    trail = tuple(path[len(RESULT):-1])
    return tuple(path[:len(RESULT)]) == RESULT and trail == ("clashgroup", "clashresults") * (len(trail) // 2)


def parse_report(data):
    decoded = data.decode("utf-8-sig")
    if "\0" in decoded or re.search(r"<!\s*(DOCTYPE|ENTITY)\b", decoded, re.I):
        raise ValueError("DTD, entity declarations and NUL bytes are forbidden.")
    path = []
    report = []
    seen = set()
    nodes = 0
    tests = 0
    units = ""
    for event, node in ET.iterparse(io.StringIO(decoded), events=("start", "end")):
        if event == "start":
            path.append(node.tag)
            nodes += 1
            if nodes > 20000 or len(path) > 24:
                raise ValueError("XML exceeds structure limits.")
            if "}" in node.tag or (nodes == 1 and node.tag != "exchange"):
                raise ValueError("Select an unnamespaced Navisworks exchange XML report.")
            if nodes == 1:
                units = text(node.get("units", ""))
            if tuple(path) == RESULT[:-1]:
                tests += 1
            continue
        if node.tag == "clashresult":
            if not valid_result_path(path) or len(report) >= 300:
                raise ValueError("Unexpected result nesting or too many clashes.")
            source_guid = text(node.get("guid", ""))
            try:
                guid = str(uuid.UUID(source_guid))
            except ValueError:
                guid = None
            if guid is not None:
                if guid in seen:
                    raise ValueError("Duplicate clash GUID.")
                seen.add(guid)
            groups = node.findall("clashobjects")
            objects = groups[0].findall("clashobject") if len(groups) == 1 else []
            source_point = node.find("clashpoint/pos3f")
            coordinates = point([float(source_point.attrib[axis]) for axis in "xyz"]) if source_point is not None else None
            report.append({
                "guid": guid, "name": text(node.get("name", "")),
                "source_status": text(node.get("status", "")).casefold(),
                "source_point": coordinates,
                "objects": [object_side(item) for item in objects] if len(objects) == 2 else [],
            })
        path.pop()
    if not tests:
        raise ValueError("No Clash Detective test found in this exchange file.")
    return units, report


def point(value):
    if (not isinstance(value, list) or len(value) != 3
            or any(type(n) not in (int, float) or not -1e6 <= n <= 1e6 for n in value)):
        raise ValueError("Bounds must contain three finite host coordinates.")
    return value


def element_snapshot(raw):
    doc = json_input(raw)
    if doc["coordinate_frame"] != FRAME or not text(doc["host_id"]):
        raise ValueError("Use a named Revit host snapshot in internal feet.")
    sources = doc["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
        raise ValueError("Use 1 to 32 source model instances.")
    index = {}
    ids = set()
    total = 0
    for source in sources:
        model = text(source["model_id"])
        prefix = source["path_prefix"]
        if not isinstance(prefix, list) or not 1 <= len(prefix) <= 20:
            raise ValueError("A source needs an exact selection-tree path prefix.")
        prefix = tuple(text(node) for node in prefix)
        if not model or not all(prefix) or prefix in index or model in ids:
            raise ValueError("Duplicate or empty source model mapping.")
        ids.add(model)
        entries = source["elements"]
        if not isinstance(entries, dict):
            raise ValueError("Use an element ID dictionary.")
        total += len(entries)
        if total > 10000:
            raise ValueError("Element snapshot exceeds the supported count.")
        elements = {}
        unique = set()
        for key, item in entries.items():
            low, high = point(item["min"]), point(item["max"])
            uid = text(item["unique_id"])
            if (not re.fullmatch(r"[1-9][0-9]{0,18}", key) or int(key) > 2**63 - 1
                    or not uid or uid in unique or not all(0 <= b - a <= 1000 for a, b in zip(low, high))
                    or low == high):
                raise ValueError("Invalid or duplicate element identity or bounds.")
            unique.add(uid)
            elements[key] = {"model_id": model, "unique_id": uid, "min": low, "max": high}
        index[prefix] = elements
    return doc["host_id"], index


def section_box(objects, index, padding):
    if len(objects) != 2:
        return None
    targets = []
    for item in objects:
        path = tuple(item["selection_path"])
        matched = [elements for prefix, elements in index.items() if path[:len(prefix)] == prefix]
        if len(matched) != 1 or item["element_id"] not in matched[0]:
            return None
        targets.append(matched[0][item["element_id"]])
    if (targets[0]["model_id"], targets[0]["unique_id"]) == (targets[1]["model_id"], targets[1]["unique_id"]):
        return None
    low = [min(a, b) - padding for a, b in zip(targets[0]["min"], targets[1]["min"])]
    high = [max(a, b) + padding for a, b in zip(targets[0]["max"], targets[1]["max"])]
    if not all(-1e6 <= a < b <= 1e6 and b - a <= 1000 for a, b in zip(low, high)):
        return None
    return {"min": low, "max": high, "targets": [
        {key: item[key] for key in ("model_id", "unique_id")} for item in targets
    ]}


def board_rows(path, *, archive=False):
    body, formats = board_cli.decode_note(json_input(local_bytes(path)))
    board = ib.parse_board(body)
    issues = board["issues"]
    numbers = {row["number"] for row in issues}
    markers = set()
    header = board["header"]
    if (header["archive"] != archive or not header["title"] or len(numbers) != len(issues)
            or (not archive and (header["next_number"] or 0) <= max(numbers, default=0))):
        raise ValueError("Invalid board header, role or issue numbers.")
    for row in issues:
        for finding in row["findings"]:
            if finding.startswith(MARKER):
                raw = finding[len(MARKER):]
                if str(uuid.UUID(raw)) != raw or raw in markers:
                    raise ValueError("Board has invalid or duplicate clash provenance.")
                markers.add(raw)
    return body, formats, issues, markers


def board_preview(path, archive, clashes):
    body, formats, existing_rows, seen = board_rows(path)
    if archive:
        _, _, _, archived = board_rows(archive, archive=True)
        if seen & archived:
            raise ValueError("Clash provenance exists on both active and archive notes.")
        seen.update(archived)
    proposals = []
    skipped = []
    for row in clashes:
        guid = row["guid"]
        if guid is None:
            continue
        if guid in seen:
            skipped.append(guid)
            continue
        title = bcf_cli.literal(row["name"])
        title = re.sub(re.escape(MARKER), "Navisworks source reference: ", title, flags=re.I)
        title = "Clash: " + (title or guid)
        issue = {"title": title, "status": "OPEN", "findings": [
            MARKER + guid,
            "Section bounds proposed for review." if row["section_box"] else "Element mapping requires review.",
        ]}
        proposals.append({"op": "add", "issue": issue})
    if not proposals:
        return None, skipped
    plan = ib.plan_batch(body, proposals, formats)
    after = ib.parse_board(plan["final_text"])["issues"]
    by_number = {row["number"]: row for row in after}
    if (len(after) != len(existing_rows) + len(proposals) or len(after) != len(by_number)
            or any(by_number.get(row["number"]) != row for row in existing_rows)):
        raise ValueError("Preview changed existing issues or issue counts.")
    for operation, request in zip(plan["operations"], proposals):
        row = by_number[int(operation.removeprefix("add #"))]
        issue = request["issue"]
        if (row["title"] != issue["title"] or row["status"] != issue["status"]
                or row["findings"] != issue["findings"] or row["assignees"] != ["@TBD"]
                or row["parent"] is not None
                or any(row[key] for key in ("element_ids", "related", "todos", "comments", "severity"))):
            raise ValueError("Preview did not preserve literal clash data.")
    return plan, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--snapshot")
    parser.add_argument("--padding-ft", type=float, default=1.0)
    parser.add_argument("--board")
    parser.add_argument("--archive")
    args = parser.parse_args(argv)
    try:
        if Path(args.report).suffix.lower() != ".xml":
            raise ValueError("Export a Navisworks XML report. HTML requires a separately verified layout.")
        if not math.isfinite(args.padding_ft) or not 0.1 <= args.padding_ft <= 20:
            raise ValueError("Use padding from 0.1 to 20 feet.")
        if args.archive and not args.board:
            raise ValueError("Supply an active board with the archive.")
        raw = local_bytes(args.report)
        units, clashes = parse_report(raw)
        snapshot = local_bytes(args.snapshot) if args.snapshot else None
        host, index = element_snapshot(snapshot) if snapshot is not None else (None, {})
        for row in clashes:
            row["section_box"] = section_box(row["objects"], index, args.padding_ft)
            row["warnings"] = []
            if row["guid"] is None:
                row["warnings"].append("Missing or invalid clash GUID.")
            if row["source_status"] not in STATUSES:
                row["warnings"].append("Unknown Navisworks status.")
            if row["section_box"] is None:
                row["warnings"].append("Both distinct elements must match one scoped Revit snapshot.")
        plan, skipped = board_preview(args.board, args.archive, clashes) if args.board else (None, [])
        report = {
            "kind": "navisworks-clash-preview", "model_write_approved": False,
            "report_sha256": hashlib.sha256(raw).hexdigest(), "source_units": units,
            "snapshot_sha256": hashlib.sha256(snapshot).hexdigest() if snapshot is not None else None,
            "host_id": host, "coordinate_frame": FRAME if host else None,
            "clashes": clashes, "plan": plan, "skipped_guids": skipped,
            "warnings": ["Archive note not checked for duplicates."] if args.board and not args.archive else [],
        }
        encoded = json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2)
        if len(encoded) > LIMIT:
            raise ValueError("Preview exceeds the supported size.")
        print(encoded)
    except OSError:
        print("Navisworks intake failed: a local input could not be opened.", file=sys.stderr)
        return 2
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError, ET.ParseError, ib.BoardError):
        # Parser and board exceptions may include raw report or model content.
        print("Navisworks intake failed: invalid input, format, identity or limit.", file=sys.stderr)
        if Path(args.report).suffix.lower() != ".xml":
            print("Export a Navisworks XML report. HTML is not supported here.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

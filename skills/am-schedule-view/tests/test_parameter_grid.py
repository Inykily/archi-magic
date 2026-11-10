import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts" / "schedule_roundtrip.py"
SAMPLE = SKILL / "assets" / "fixtures" / "parameter-grid.sample.json"
LARGE_ID = "9007199254740993"


def cli(*args, ok=True):
    result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                            capture_output=True, text=True)
    if ok:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert result.stderr.startswith("Error: ")
    return result.stdout


def packet(path, edits):
    path.write_text(json.dumps({
        "kind": "schedule-grid-edits",
        "snapshot_sha256": hashlib.sha256(SAMPLE.read_bytes()).hexdigest(),
        "edits": edits,
    }), encoding="utf-8")


def test_csv_and_grid_preview_parity(tmp_path):
    sheet, grid_packet = tmp_path / "schedule.csv", tmp_path / "grid.json"
    cli("export", "--schedule", SAMPLE, "--out", sheet)
    with sheet.open(encoding="utf-8", newline="") as source:
        header, first, second = list(csv.reader(source))
    assert first[0] == LARGE_ID
    first[1:] = ["D01-B", "Café\r\n北", "32 m²"]
    second[2] = "  "  # The existing comparison disregards edge whitespace.
    with sheet.open("w", encoding="utf-8-sig", newline="") as output:
        csv.writer(output).writerows([header, second, first])
    packet(grid_packet, [
        {"id": LARGE_ID, "field": "Area", "value": first[3]},
        {"id": LARGE_ID, "field": "Comments", "value": "Café\n北"},
        {"id": LARGE_ID, "field": "Mark", "value": first[1]},
    ])
    excel = cli("preview", "--original", SAMPLE, "--edited", sheet)
    grid = cli("preview-grid", "--original", SAMPLE, "--edited", grid_packet)
    assert grid == excel == cli("preview-grid", "--original", SAMPLE, "--edited", grid_packet)
    preview = json.loads(grid)
    assert preview["kind"] == "change-preview"
    assert preview["keyColumn"] == "Element ID"
    assert preview["columns"] == ["Element ID", "Mark", "Comments", "Area"]
    assert preview["changedColumns"] == ["Mark", "Comments", "Area"]
    assert preview["before"] == [[LARGE_ID, "D01", "Review", "25 m²"], ["102", "D02", "", "31 m²"]]
    assert preview["after"] == [[LARGE_ID, "D01-B", "Café\n北", "32 m²"], ["102", "D02", "", "31 m²"]]
    assert preview["ownership_ids"] == [LARGE_ID]
    assert preview["steps"] == []
    assert preview["review_only"] is True
    assert preview["blocked"] is True
    assert preview["warnings"] == [{
        "kind": "blocking", "row": LARGE_ID, "field": "Area", "blocking": True,
        "message": "Field 'Area' is read-only or calculated in Revit. Cannot write back.",
        "text": "Field 'Area' is read-only or calculated in Revit. Cannot write back.",
    }]
    assert preview["counts"] == {"changed": 3, "unchanged": 3, "warnings": 1}


@pytest.mark.parametrize("edit", [
    {"id": "100", "field": "Mark", "value": "Other ID"},
    {"id": LARGE_ID, "field": "Other", "value": "Other field"},
    {"id": int(LARGE_ID), "field": "Mark", "value": "Numeric ID"},
    {"id": LARGE_ID, "field": "Mark", "value": None},
    {"id": LARGE_ID, "field": "Mark", "value": "x" * 2001},
])
def test_rejects_malformed_edits(tmp_path, edit):
    path = tmp_path / "grid.json"
    packet(path, [edit])
    cli("preview-grid", "--original", SAMPLE, "--edited", path, ok=False)


def test_rejects_wrong_snapshot_and_duplicate_edits(tmp_path):
    path = tmp_path / "grid.json"
    edit = {"id": LARGE_ID, "field": "Mark", "value": "Updated"}
    packet(path, [edit, edit])
    cli("preview-grid", "--original", SAMPLE, "--edited", path, ok=False)
    packet(path, [edit])
    other = tmp_path / "other.json"
    other.write_bytes(SAMPLE.read_bytes() + b"\n")
    cli("preview-grid", "--original", other, "--edited", path, ok=False)
    path.write_text(path.read_text().replace('"edits":', '"edits": [], "edits":'))
    cli("preview-grid", "--original", SAMPLE, "--edited", path, ok=False)


def test_rejects_duplicate_csv_id(tmp_path):
    sheet = tmp_path / "schedule.csv"
    cli("export", "--schedule", SAMPLE, "--out", sheet)
    lines = sheet.read_bytes().splitlines(keepends=True)
    sheet.write_bytes(b"".join(lines + lines[1:2]))
    cli("preview", "--original", SAMPLE, "--edited", sheet, ok=False)

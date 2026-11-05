# -*- coding: utf-8 -*-
"""Tests for schedule_roundtrip.py (issue #128: Excel round trip for schedules).

Run:
    python -m pytest skills/am-schedule-view/tests/test_schedule_roundtrip.py
"""

import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROUNDTRIP_SCRIPT = os.path.join(HERE, "..", "scripts", "schedule_roundtrip.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import schedule_roundtrip as sr


def test_export_and_import_schedule_csv(tmp_path):
    csv_file = str(tmp_path / "doors.csv")
    sched = {
        "columns": ["Mark", "Fire Rating", "Comments"],
        "rows": [
            {"id": "101", "Mark": "D101", "Fire Rating": "20 MIN", "Comments": ""},
            {"id": "102", "Mark": "D102", "Fire Rating": "45 MIN", "Comments": "Verify"},
        ],
    }
    sr.export_schedule_csv(sched, csv_file)
    assert os.path.exists(csv_file)

    headers, rows = sr.parse_imported_csv(csv_file)
    assert "Element ID" in headers
    assert len(rows) == 2
    assert rows[0]["Element ID"] == "101"
    assert rows[0]["Mark"] == "D101"


def test_three_changed_cells_produce_three_row_preview():
    orig_rows = [
        {"id": "1", "Mark": "D101", "Comments": "Old Note", "Frame Type": "F1"},
        {"id": "2", "Mark": "D102", "Comments": "Old Note 2", "Frame Type": "F1"},
    ]

    edited_rows = [
        # Cell 1: Mark changed, Cell 2: Comments changed
        {"Element ID": "1", "Mark": "D101-A", "Comments": "Updated Note", "Frame Type": "F1"},
        # Cell 3: Frame Type changed
        {"Element ID": "2", "Mark": "D102", "Comments": "Old Note 2", "Frame Type": "F2"},
    ]

    preview = sr.diff_schedule_import(orig_rows, edited_rows)
    assert preview["counts"]["changed"] == 3
    assert len(preview["rows"]) == 3
    assert preview["blocked"] is False
    assert len(preview["warnings"]) == 0

    fields = [r["Field"] for r in preview["rows"]]
    assert "Mark" in fields
    assert "Comments" in fields
    assert "Frame Type" in fields


def test_changed_read_only_field_shows_blocking_warning():
    orig_rows = [
        {"id": "10", "Name": "Office", "Area": "150.0", "Department": "Admin"},
    ]
    # User edited Area (which is read-only / calculated in Revit)
    edited_rows = [
        {"Element ID": "10", "Name": "Office", "Area": "200.0", "Department": "Admin"},
    ]

    preview = sr.diff_schedule_import(orig_rows, edited_rows)
    assert preview["counts"]["changed"] == 1
    assert preview["blocked"] is True
    assert len(preview["warnings"]) == 1
    w = preview["warnings"][0]
    assert w["kind"] == "blocking"
    assert w["field"] == "Area"
    assert "read-only or calculated" in w["message"]


def test_cli_execution_end_to_end(tmp_path):
    orig_file = str(tmp_path / "orig.json")
    edited_csv = str(tmp_path / "edited.csv")
    preview_out = str(tmp_path / "preview.json")

    with open(orig_file, "w") as f:
        json.dump([{"id": "50", "Comments": "Before"}], f)

    with open(edited_csv, "w") as f:
        writer = csv.writer(f)
        writer.writerow(["Element ID", "Comments"])
        writer.writerow(["50", "After"])

    proc = subprocess.run([
        sys.executable, ROUNDTRIP_SCRIPT, "preview",
        "--original", orig_file,
        "--edited", edited_csv,
        "--out", preview_out,
    ], capture_output=True, text=True)
    assert proc.returncode == 0
    with open(preview_out, "r") as f:
        data = json.load(f)
    assert data["counts"]["changed"] == 1
    assert data["rows"][0]["Before"] == "Before"
    assert data["rows"][0]["After"] == "After"

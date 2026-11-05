# -*- coding: utf-8 -*-
"""Tests for model_compare.py (issue #183: model version compare).

Run:
    python -m pytest skills/am-safe-change/tests/test_model_compare.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_COMPARE_SCRIPT = os.path.join(HERE, "..", "scripts", "model_compare.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import model_compare as mc


def test_compare_snapshots_exact_detection():
    snap_before = [
        {"id": 101, "category": "OST_Walls", "name": "Basic Wall", "location": "(0, 0, 0)", "parameters": {"Fire Rating": "1 HR"}},
        {"id": 102, "category": "OST_Doors", "name": "Single Flush", "location": "(10, 0, 0)", "parameters": {"Mark": "D101"}},
        {"id": 103, "category": "OST_Rooms", "name": "Storage", "location": "(20, 20, 0)", "parameters": {"Department": "Facilities"}},
    ]

    snap_after = [
        # 101 moved
        {"id": 101, "category": "OST_Walls", "name": "Basic Wall", "location": "(0, 5, 0)", "parameters": {"Fire Rating": "1 HR"}},
        # 102 parameter modified
        {"id": 102, "category": "OST_Doors", "name": "Single Flush", "location": "(10, 0, 0)", "parameters": {"Mark": "D101-Renamed"}},
        # 103 was deleted (not present)
        # 104 is newly added
        {"id": 104, "category": "OST_Windows", "name": "Fixed 36x48", "location": "(15, 0, 0)", "parameters": {"Mark": "W101"}},
    ]

    diff = mc.compare_snapshots(snap_before, snap_after)
    s = diff["summary"]

    assert s["added"] == 1
    assert s["deleted"] == 1
    assert s["modified"] == 1
    assert s["moved"] == 1
    assert s["total_changes"] == 4

    assert diff["added"][0]["id"] == 104
    assert diff["deleted"][0]["id"] == 103

    mod = diff["modified"][0]
    assert mod["id"] == "102"
    assert mod["parameter"] == "Mark"
    assert mod["old_value"] == "D101"
    assert mod["new_value"] == "D101-Renamed"

    mv = diff["moved"][0]
    assert mv["id"] == "101"
    assert mv["old_location"] == "(0, 0, 0)"
    assert mv["new_location"] == "(0, 5, 0)"


def test_recreated_element_with_new_id_reported_as_delete_plus_add():
    """An element deleted and re-created is reported as delete + add, not as a modification."""
    snap_before = [
        {"id": 201, "category": "OST_Walls", "name": "Partition A", "location": "(0, 0, 0)"},
    ]
    # Re-created with same name/location but different ID 202
    snap_after = [
        {"id": 202, "category": "OST_Walls", "name": "Partition A", "location": "(0, 0, 0)"},
    ]

    diff = mc.compare_snapshots(snap_before, snap_after)
    assert diff["summary"]["deleted"] == 1
    assert diff["summary"]["added"] == 1
    assert diff["summary"]["modified"] == 0
    assert diff["summary"]["moved"] == 0
    assert diff["deleted"][0]["id"] == 201
    assert diff["added"][0]["id"] == 202


def test_cli_execution_markdown_and_json(tmp_path):
    f_before = str(tmp_path / "before.json")
    f_after = str(tmp_path / "after.json")
    f_out = str(tmp_path / "report.md")

    with open(f_before, "w") as f:
        json.dump([{"id": 1, "category": "OST_Walls", "parameters": {"Comments": "Old"}}], f)
    with open(f_after, "w") as f:
        json.dump([{"id": 1, "category": "OST_Walls", "parameters": {"Comments": "New"}}], f)

    # CLI Markdown output to file
    proc = subprocess.run([
        sys.executable, MODEL_COMPARE_SCRIPT, f_before, f_after, "--out", f_out
    ], capture_output=True, text=True)
    assert proc.returncode == 0
    with open(f_out, "r") as f:
        content = f.read()
    assert "# Model Version Compare Report" in content
    assert "| 1 | OST_Walls | Comments | Old | New |" in content

    # CLI JSON output to stdout
    proc_json = subprocess.run([
        sys.executable, MODEL_COMPARE_SCRIPT, f_before, f_after, "--json"
    ], capture_output=True, text=True)
    assert proc_json.returncode == 0
    data = json.loads(proc_json.stdout)
    assert data["summary"]["modified"] == 1

# -*- coding: utf-8 -*-
"""Tests for publish_preflight.py (issue #135: publish-set preflight checker).

Run:
    python -m pytest skills/am-model-health/tests/test_publish_preflight.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PREFLIGHT_SCRIPT = os.path.join(HERE, "..", "scripts", "publish_preflight.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import publish_preflight as pp


def test_clean_publish_set_ready():
    sheets = [
        {
            "id": 101,
            "sheet_number": "A101",
            "parameters": {
                "Sheet Number": "A101",
                "Sheet Name": "First Floor Plan",
                "Drawn By": "AB",
                "Checked By": "CD",
            },
            "placed_views": [
                {"name": "Level 1 Floor Plan", "crop_box_visible": False},
            ],
        }
    ]
    res = pp.evaluate_publish_preflight(sheets)
    assert res["ready_to_publish"] is True
    assert res["summary"]["errors"] == 0
    assert res["summary"]["warnings"] == 0
    assert len(res["findings"]) == 0


def test_empty_sheet_blocks_publish():
    sheets = [
        {
            "id": 102,
            "sheet_number": "A102",
            "parameters": {
                "Sheet Number": "A102",
                "Sheet Name": "Second Floor Plan",
                "Drawn By": "AB",
                "Checked By": "CD",
            },
            "placed_views": [],  # Empty!
        }
    ]
    res = pp.evaluate_publish_preflight(sheets)
    assert res["ready_to_publish"] is False
    assert res["summary"]["errors"] == 1
    f = res["findings"][0]
    assert f["code"] == "PRE-01"
    assert "Empty sheet" in f["message"]


def test_missing_metadata_and_visible_crop_warnings():
    sheets = [
        {
            "id": 103,
            "sheet_number": "A103",
            "parameters": {
                "Sheet Number": "A103",
                "Sheet Name": "Reflected Ceiling Plan",
                "Drawn By": "AB",
                "Checked By": "",  # Missing!
            },
            "placed_views": [
                {"name": "Level 1 RCP", "crop_box_visible": True},  # Crop visible!
            ],
        }
    ]
    res = pp.evaluate_publish_preflight(sheets)
    assert res["summary"]["warnings"] == 2
    codes = [f["code"] for f in res["findings"]]
    assert "PRE-02" in codes
    assert "PRE-03" in codes


def test_cli_execution_end_to_end(tmp_path):
    data_file = str(tmp_path / "publish_set.json")
    out_file = str(tmp_path / "out.json")

    with open(data_file, "w") as f:
        json.dump({
            "sheets": [
                {"id": 1, "sheet_number": "A001", "placed_views": [], "parameters": {}},
            ],
            "unplaced_views": [
                {"id": 2, "name": "Detail 1"},
            ],
        }, f)

    proc = subprocess.run([
        sys.executable, PREFLIGHT_SCRIPT, "check",
        "--data", data_file,
        "--out", out_file,
    ], capture_output=True, text=True)
    assert proc.returncode == 0
    with open(out_file, "r") as f:
        data = json.load(f)
    assert data["ready_to_publish"] is False
    assert data["summary"]["errors"] == 1
    assert data["summary"]["info"] == 1

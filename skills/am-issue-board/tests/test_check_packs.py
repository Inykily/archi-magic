# -*- coding: utf-8 -*-
"""Tests for check_packs.py (issue #180: team-authored rules with severity).

Run:
    python -m pytest skills/am-issue-board/tests/test_check_packs.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK_PACKS_SCRIPT = os.path.join(HERE, "..", "scripts", "check_packs.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import check_packs as cp


def test_list_builtin_packs():
    packs = cp.list_builtin_packs()
    filenames = [p["file"] for p in packs]
    assert "door-data.json" in filenames
    assert "room-data.json" in filenames
    assert "sheet-data.json" in filenames


def test_condition_operators():
    assert cp.evaluate_condition("Value", "not_empty") is True
    assert cp.evaluate_condition("", "not_empty") is False
    assert cp.evaluate_condition(None, "not_empty") is False

    assert cp.evaluate_condition("", "empty") is True
    assert cp.evaluate_condition("X", "empty") is False

    assert cp.evaluate_condition("ABC", "contains", "B") is True
    assert cp.evaluate_condition("ABC", "contains", "Z") is False

    assert cp.evaluate_condition("ABC", "not_contains", "TBD") is True
    assert cp.evaluate_condition("Door TBD", "not_contains", "TBD") is False

    assert cp.evaluate_condition("100", "greater_than", 50) is True
    assert cp.evaluate_condition("30", "greater_than", 50) is False


def test_clean_model_reports_zero_findings():
    pack = cp.load_pack("door-data.json")
    clean_doors = [
        {
            "id": 101,
            "name": "Single Flush 36x84",
            "category": "OST_Doors",
            "parameters": {"Fire Rating": "45 MIN", "Frame Type": "F1", "Comments": "Verified"},
        },
        {
            "id": 102,
            "name": "Single Flush 36x84",
            "category": "OST_Doors",
            "parameters": {"Fire Rating": "20 MIN", "Frame Type": "F2", "Comments": "Approved"},
        },
    ]
    res = cp.evaluate_pack(pack, clean_doors)
    assert res["summary"]["total"] == 0
    assert res["summary"]["error"] == 0
    assert res["summary"]["warning"] == 0
    assert res["summary"]["info"] == 0
    assert len(res["findings"]) == 0


def test_seeded_failure_reports_exact_severity():
    pack = cp.load_pack("door-data.json")
    doors_with_issues = [
        {
            "id": 201,
            "name": "Door Missing Fire Rating",
            "category": "OST_Doors",
            "parameters": {"Fire Rating": "", "Frame Type": "F1", "Comments": "Normal"},
        },
        {
            "id": 202,
            "name": "Door with TBD",
            "category": "OST_Doors",
            "parameters": {"Fire Rating": "90 MIN", "Frame Type": "", "Comments": "Check hardware TBD"},
        },
    ]
    res = cp.evaluate_pack(pack, doors_with_issues)
    assert res["summary"]["total"] == 3
    assert res["summary"]["error"] == 1  # Door 201 missing Fire Rating
    assert res["summary"]["warning"] == 1  # Door 202 missing Frame Type
    assert res["summary"]["info"] == 1  # Door 202 TBD comment

    err = [f for f in res["findings"] if f["severity"] == "error"][0]
    assert err["element_id"] == 201
    assert err["rule_id"] == "DOOR-01"


def test_custom_rule_file_runs_with_no_code_change(tmp_path):
    custom_pack_path = str(tmp_path / "custom-clearance.json")
    with open(custom_pack_path, "w") as f:
        json.dump({
            "name": "Custom Clearance Rules",
            "version": "1.0",
            "rules": [
                {
                    "id": "CLR-01",
                    "category": "OST_MechanicalEquipment",
                    "parameter": "Front Clearance",
                    "condition": "greater_than",
                    "value": "3.0",
                    "severity": "error",
                    "message": "Equipment front clearance must exceed 3.0 ft",
                    "fix_hint": "Adjust placement or increase clearance dimension",
                }
            ],
        }, f)

    pack = cp.load_pack(custom_pack_path)
    equipment = [
        {"id": 301, "category": "OST_MechanicalEquipment", "parameters": {"Front Clearance": "2.5"}},
        {"id": 302, "category": "OST_MechanicalEquipment", "parameters": {"Front Clearance": "4.0"}},
    ]
    res = cp.evaluate_pack(pack, equipment)
    assert res["summary"]["total"] == 1
    assert res["findings"][0]["element_id"] == 301
    assert res["findings"][0]["rule_id"] == "CLR-01"


def test_to_issue_board_findings():
    pack = cp.load_pack("room-data.json")
    rooms = [
        {"id": 401, "name": "Office 101", "category": "OST_Rooms", "parameters": {"Department": "", "Occupancy": ""}},
    ]
    eval_res = cp.evaluate_pack(pack, rooms)
    board_findings = cp.to_issue_board_findings(eval_res)
    assert len(board_findings) == 2
    assert board_findings[0]["code"] == "ROOM-01"
    assert board_findings[0]["severity"] == "error"
    assert board_findings[0]["element_id"] == 401


def test_cli_execution(tmp_path):
    data_file = str(tmp_path / "elements.json")
    with open(data_file, "w") as f:
        json.dump({
            "elements": [
                {"id": 501, "name": "Sheet A101", "category": "OST_Sheets", "parameters": {"Sheet Name": "", "Drawn By": "AB"}},
            ]
        }, f)

    proc = subprocess.run([
        sys.executable, CHECK_PACKS_SCRIPT, "evaluate",
        "--pack", "sheet-data.json",
        "--data", data_file,
    ], capture_output=True, text=True)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["summary"]["error"] == 1  # Missing Sheet Name

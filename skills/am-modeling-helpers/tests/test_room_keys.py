# -*- coding: utf-8 -*-
"""Tests for scripts/lib/room_keys.py and scripts/room_key_plan.py (no Revit)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import room_keys as rk  # noqa: E402
import room_key_plan  # noqa: E402

PARAM = "Floor Finish"


def target(room_id, number, value, read_only, key_id=None, key_name=None):
    return {"id": room_id, "number": number, "name": "Room %s" % number,
            "keys": {"Room Style": {"key_id": key_id, "key_name": key_name}},
            "values": {PARAM: {"found": True, "value": value, "read_only": read_only}}}


def read(targets, usage, complete=True):
    return {
        "kind": "room-key-read",
        "key_schedules": [{"id": 900, "name": "Room Style Key", "key_parameter": "Room Style",
                           "fields": [PARAM, "Wall Finish"], "key_names": ["SHARED", "OWN"]}],
        "targets": targets,
        "key_usage": {"Room Style": usage},
        "key_rows": {"50": {"name": "SHARED", "values": {PARAM: "FIN-1"}},
                     "60": {"name": "OWN", "values": {PARAM: "FIN-2"}}},
        "scan_complete": complete,
    }


def sample(complete=True):
    targets = [
        target(1, "101", "FIN-1", True, 50, "SHARED"),
        target(2, "102", "FIN-1", True, 50, "SHARED"),
        target(3, "103", "FIN-2", True, 60, "OWN"),
        target(4, "104", "FIN-9", False),
        target(5, "105", "X", True),
    ]
    usage = {"50": {"count": 40, "room_ids": [1, 2] + list(range(100, 138)), "truncated": False},
             "60": {"count": 1, "room_ids": [3], "truncated": False}}
    return read(targets, usage, complete)


def test_states_and_groups():
    analysis = rk.analyze(sample(), PARAM)
    states = dict((r["room_id"], r["state"]) for r in analysis["rooms"])
    assert states == {1: rk.KEY_DRIVEN, 2: rk.KEY_DRIVEN, 3: rk.KEY_DRIVEN,
                      4: rk.WRITABLE, 5: rk.READ_ONLY_OTHER}
    shared, own = analysis["groups"]
    assert shared["key_name"] == "SHARED"
    assert shared["other_room_count"] == 38
    assert shared["recommended"] == rk.NEW_KEY
    assert own["other_room_count"] == 0
    assert own["recommended"] == rk.EDIT_KEY


def test_missing_parameter_and_field_not_in_key_schedule():
    data = sample()
    data["targets"][0]["values"] = {}
    data["key_schedules"][0]["fields"] = ["Wall Finish"]
    states = dict((r["room_id"], r["state"]) for r in rk.analyze(data, PARAM)["rooms"])
    assert states[1] == rk.MISSING
    assert states[2] == rk.READ_ONLY_OTHER


def test_incomplete_scan_never_recommends_editing_a_key():
    analysis = rk.analyze(sample(complete=False), PARAM)
    assert all(g["recommended"] == rk.NEW_KEY for g in analysis["groups"])
    assert analysis["warnings"]
    preview = rk.build_preview(sample(False), analysis, rk.EDIT_KEY, "FIN-3", key_id="60")
    assert preview["blocked"]


def test_new_key_preview_assigns_only_target_rooms():
    data = sample()
    analysis = rk.analyze(data, PARAM)
    preview = rk.build_preview(data, analysis, rk.NEW_KEY, "FIN-3", key_id="50", new_key_name="SHARED B")
    assert not preview["blocked"]
    assert preview["changedColumns"] == ["Key", PARAM]
    assert [row[0] for row in preview["after"]] == ["new", 1, 2]
    assert preview["after"][1][3:] == ["SHARED B", "FIN-3"]
    assert preview["ownership_ids"] == [900, 1, 2]
    add, assign = preview["steps"]
    assert add == {"op": "add_key_row", "schedule_id": 900, "copy_from_key_id": 50,
                   "key_name": "SHARED B", "set": {PARAM: "FIN-3"}}
    assert assign["room_ids"] == [1, 2]


def test_new_key_name_must_be_new():
    data = sample()
    analysis = rk.analyze(data, PARAM)
    for name in ("", "OWN", "SHARED"):
        preview = rk.build_preview(data, analysis, rk.NEW_KEY, "FIN-3", key_id="50", new_key_name=name)
        assert preview["blocked"]


def test_edit_shared_key_warns_about_other_rooms():
    data = sample()
    analysis = rk.analyze(data, PARAM)
    preview = rk.build_preview(data, analysis, rk.EDIT_KEY, "FIN-3", key_id="50")
    assert not preview["blocked"]
    assert "38 rooms" in preview["warnings"][0]["text"]
    assert preview["before"][0] == [50, "Key row", "", "SHARED", "FIN-1"]
    assert preview["steps"] == [{"op": "set_key_parameter", "key_id": 50, "parameter": PARAM, "value": "FIN-3"}]


def test_set_rooms_preview_covers_writable_rooms_only():
    data = sample()
    preview = rk.build_preview(data, rk.analyze(data, PARAM), rk.SET_ROOMS, "FIN-3")
    assert [row[0] for row in preview["before"]] == [4]
    assert preview["steps"][0]["room_ids"] == [4]


def test_cli_report_and_preview(tmp_path, capsys):
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"result": {"payload": json.dumps(sample())}}))
    assert room_key_plan.main(["report", "--read", str(path), "--parameter", PARAM]) == 1
    assert "Recommended: new-key" in capsys.readouterr().out
    out = tmp_path / "preview.json"
    code = room_key_plan.main(["preview", "--read", str(path), "--parameter", PARAM, "--value", "FIN-3",
                               "--option", "new-key", "--key", "50", "--new-key-name", "SHARED B",
                               "--out", str(out)])
    assert code == 0
    assert json.loads(out.read_text())["kind"] == "change-preview"
    assert room_key_plan.main(["preview", "--read", str(path), "--parameter", PARAM,
                               "--value", "FIN-3", "--option", "edit-key"]) == 2
    assert room_key_plan.main(["preview", "--read", str(path), "--parameter", PARAM, "--value", "FIN-3",
                               "--option", "edit-key", "--key", "777"]) == 2

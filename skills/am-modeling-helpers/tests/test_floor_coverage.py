# -*- coding: utf-8 -*-
"""Tests for scripts/lib/floor_coverage.py and scripts/floor_coverage_plan.py (no Revit)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import floor_coverage as fc  # noqa: E402
import floor_coverage_plan  # noqa: E402

FINISH_A, FINISH_B, SLAB = 11, 12, 99


def floor(fid, type_id, top, structural=False, offset=0.0, **extra):
    row = {"id": fid, "uid": "uid-%d" % fid, "type_id": type_id, "type_name": "Type %d" % type_id,
           "level_name": "Level 1", "is_structural": structural, "height_offset_ft": offset,
           "thickness_ft": 0.02, "top_area_sf": top}
    row.update(extra)
    return row


def pair(room_id, floor_id, area, status="ok"):
    return {"room_id": room_id, "floor_id": floor_id, "overlap_sf": area, "overlap_cf": area * 0.02,
            "status": status}


def sample(complete=True):
    """Room 1 (100 sf) and room 2 (50 sf).

    Floor 201: finish, only in room 1.
    Floor 202: finish, 40 sf in room 2 and 60 sf outside the rooms (mixed).
    Floor 203: finish, a 1 sf strip under the wall of room 1 (edge only).
    Floor 300: structural slab under both rooms.
    """
    return {
        "kind": "floor-room-coverage-read", "complete": complete,
        "pending_room_ids": [] if complete else [3],
        "rooms": [{"id": 1, "number": "101", "area_sf": 100.0, "status": "read"},
                  {"id": 2, "number": "102", "area_sf": 50.0, "status": "read"},
                  {"id": 4, "number": "104", "status": "excluded", "reason": "open_boundary_loop"}],
        "floors": [floor(201, FINISH_A, 100.0), floor(202, FINISH_A, 100.0),
                   floor(203, FINISH_B, 60.0), floor(300, SLAB, 5000.0, structural=True)],
        "pairs": [pair(1, 201, 99.5), pair(2, 202, 40.0), pair(1, 203, 1.0),
                  pair(1, 300, 100.0), pair(2, 300, 50.0)],
    }


def by_id(rows):
    return dict((r["id"], r) for r in rows)


def test_floor_actions_and_shares():
    floors = by_id(fc.summarize(sample())["floors"])
    assert floors[201]["action"] == fc.RETYPE_WHOLE
    assert floors[202]["action"] == fc.SPLIT_OR_ASK
    assert abs(floors[202]["share_in_scope"] - 0.4) < 1e-9
    assert floors[202]["outside_sf"] == 60.0
    assert floors[203]["action"] == fc.EDGE_ONLY
    assert floors[300]["action"] == fc.NEVER_CHANGE
    assert floors[300]["protected_reason"] == "structural"


def test_finish_types_protect_other_types():
    floors = by_id(fc.summarize(sample(), finish_type_ids=[FINISH_A])["floors"])
    assert floors[203]["role"] == fc.PROTECTED
    assert floors[203]["protected_reason"] == "not a finish floor type"
    assert floors[201]["role"] == fc.FINISH


def test_room_coverage_gap_and_excluded_room():
    rooms = by_id(fc.summarize(sample())["rooms"])
    assert rooms[1]["verdict"] == "ok"  # 99.5 + 1.0 of 100 sf
    assert rooms[2]["verdict"] == "gap"  # 40 of 50 sf
    assert [f["floor_id"] for f in rooms[2]["protected_floors"]] == [300]
    assert rooms[4]["verdict"] == "excluded"


def test_overlapping_finish_floors_are_double():
    data = sample()
    data["floors"].append(floor(204, FINISH_B, 100.0, offset=0.0208))
    data["pairs"].append(pair(1, 204, 100.0))
    summary = fc.summarize(data)
    assert by_id(summary["rooms"])[1]["verdict"] == "double"
    assert "Highlighted floors overlap" in summary["warnings"][0]


def test_one_question_per_floor_in_order():
    asks = fc.questions(fc.summarize(sample()))
    assert [a["floor_id"] for a in asks] == [201, 202]
    assert asks[0]["recommended"] == fc.RETYPE
    assert asks[1]["recommended"] == fc.SPLIT
    assert "40%" in asks[1]["text"]
    assert "60.0 sf outside" in asks[1]["text"]


def test_split_preview_keeps_the_rest_and_never_touches_the_slab():
    summary = fc.summarize(sample())
    preview = fc.build_preview(summary, {202: fc.SPLIT, 201: fc.RETYPE}, 77, "New finish")
    assert not preview["blocked"]
    assert [row[0] for row in preview["before"]] == ["201", "202:2", "202:rest"]
    assert preview["after"][1][-1] == "New finish"
    assert preview["after"][2][-1] == "Type 11"  # the rest keeps its type
    assert [s["op"] for s in preview["steps"]] == ["retype_floor", "split_floor_by_rooms"]
    assert preview["steps"][1]["rest_type_id"] == FINISH_A
    assert preview["ownership_ids"] == [201, 202]
    assert all(300 not in (s.get("floor_id"),) for s in preview["steps"])
    assert any("Protected floors" in n and "300" in n for n in preview["notes"])


def test_decision_for_structural_slab_is_blocked():
    preview = fc.build_preview(fc.summarize(sample()), {300: fc.RETYPE}, 77, "New finish")
    assert preview["blocked"]
    assert preview["steps"] == []


def test_preview_blocks_without_type_or_with_incomplete_read():
    assert fc.build_preview(fc.summarize(sample()), {201: fc.RETYPE}, None, None)["blocked"]
    assert fc.build_preview(fc.summarize(sample(False)), {201: fc.RETYPE}, 77, "New")["blocked"]


def test_failed_boolean_makes_floor_unresolved():
    data = sample()
    data["pairs"].append(pair(2, 201, 0.0, status="boolean_failed"))
    floors = by_id(fc.summarize(data)["floors"])
    assert floors[201]["action"] == fc.UNRESOLVED
    assert fc.build_preview(fc.summarize(data), {201: fc.RETYPE}, 77, "New")["blocked"]


def test_retype_of_mixed_floor_warns_about_area_outside():
    preview = fc.build_preview(fc.summarize(sample()), {202: fc.RETYPE}, 77, "New")
    assert not preview["blocked"]
    assert "60.0 sf" in preview["warnings"][0]["text"]


def test_cli_summary_and_preview(tmp_path, capsys):
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"payload": json.dumps(sample())}))
    assert floor_coverage_plan.main(["summary", "--read", str(path)]) == 0
    assert "Question 2" in capsys.readouterr().out
    out = tmp_path / "preview.json"
    code = floor_coverage_plan.main(["preview", "--read", str(path), "--decide", "202=split",
                                     "--new-type-id", "77", "--new-type-name", "New", "--out", str(out)])
    assert code == 0
    assert json.loads(out.read_text())["steps"][0]["op"] == "split_floor_by_rooms"
    assert floor_coverage_plan.main(["preview", "--read", str(path), "--decide", "300=retype",
                                     "--new-type-id", "77", "--new-type-name", "New"]) == 1
    assert floor_coverage_plan.main(["preview", "--read", str(path), "--decide", "202=paint",
                                     "--new-type-id", "77", "--new-type-name", "New"]) == 2
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps(sample(False)))
    assert floor_coverage_plan.main(["summary", "--read", str(incomplete)]) == 1

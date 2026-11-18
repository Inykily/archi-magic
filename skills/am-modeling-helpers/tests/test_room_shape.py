# -*- coding: utf-8 -*-
"""Tests for scripts/lib/room_shape.py and scripts/room_shape_report.py (no Revit)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import room_shape as rs  # noqa: E402
import room_shape_report  # noqa: E402


def rect(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def room(loops, location, area=None, **extra):
    row = {"id": 1, "number": "101", "name": "Room", "status": "read", "loops": loops,
           "location": location, "area_sf": area}
    row.update(extra)
    return row


def codes(row):
    return sorted(f["code"] for f in row["flags"])


def test_shape_metrics_finds_hole_by_containment_not_loop_order():
    hole_first = [rect(2, 2, 4, 4), rect(0, 0, 10, 10)]
    m = rs.shape_metrics(hole_first)
    assert m["hole_count"] == 1
    assert m["net_area_sf"] == 96.0
    assert m["perimeter_ft"] == 48.0
    assert abs(m["mean_width_ft"] - 4.0) < 1e-9


def test_locate_point_uses_even_odd_rule():
    loops = [rect(0, 0, 10, 10), rect(2, 2, 4, 4)]
    assert rs.locate_point((1, 1), loops) == "inside"
    assert rs.locate_point((3, 3), loops) == "outside"  # inside the hole
    assert rs.locate_point((20, 1), loops) == "outside"
    assert rs.locate_point((0, 5), loops) == "on_boundary"


def test_normal_room_is_ok():
    row = rs.check_room(room([rect(0, 0, 12, 10)], [6, 5, 0], area=120.0))
    assert row["verdict"] == "ok"
    assert row["flags"] == []
    assert row["location_point"] == "inside"


def test_three_inch_ring_with_point_outside_is_blocked():
    # Field case: outer loop = building outline, hole = roof outline, 3 in wide ring.
    outer = rect(0, 0, 100, 60)
    hole = rect(0.25, 0.25, 99.75, 59.75)
    row = rs.check_room(room([outer, hole], [50, 30, 0], area=79.75,
                             loop_sources=[{"categories": ["linked model"]}, {"categories": ["Floors"]}]))
    assert row["verdict"] == "block"
    assert "point_outside" in codes(row)
    assert "ring" in codes(row)
    assert "narrow" not in codes(row)
    assert abs(row["mean_width_in"] - 3.0) < 0.05
    assert row["loop_sources"][1]["categories"] == ["Floors"]


def test_long_strip_is_narrow():
    row = rs.check_room(room([rect(0, 0, 40, 0.5)], [20, 0.25, 0], area=20.0))
    assert "narrow" in codes(row)
    assert row["verdict"] == "block"


def test_tiny_and_unplaced_and_excluded_rooms_block():
    tiny = rs.check_room(room([rect(0, 0, 1, 1)], [0.5, 0.5, 0], area=1.0))
    assert "tiny" in codes(tiny)
    no_point = rs.check_room(room([rect(0, 0, 10, 10)], None, area=100.0))
    assert codes(no_point) == ["no_location_point"]
    excluded = rs.check_room({"id": 3, "status": "excluded", "reason": "no_boundary"})
    assert excluded["verdict"] == "block"
    assert codes(excluded) == ["no_boundary"]


def test_area_mismatch_and_revit_point_check_are_warnings():
    row = rs.check_room(room([rect(0, 0, 10, 10)], [5, 5, 0], area=120.0, revit_point_in_room=False))
    assert row["verdict"] == "warn"
    assert codes(row) == ["area_mismatch", "revit_point_check_differs"]


def test_closing_point_is_dropped():
    loop = rect(0, 0, 10, 10) + [[0, 0]]
    assert rs.shape_metrics([loop])["perimeter_ft"] == 40.0


def test_report_counts_and_cli_exit_codes(tmp_path):
    read = {"kind": "room-shape-read", "complete": False, "pending_room_ids": [9],
            "rooms": [room([rect(0, 0, 12, 10)], [6, 5, 0], area=120.0),
                      dict(room([rect(0, 0, 40, 0.5)], [20, 0.25, 0], area=20.0), id=2)]}
    report = rs.report(read)
    assert report["counts"] == {"rooms": 2, "ok": 1, "warn": 0, "block": 1}
    assert not report["complete"]
    path = tmp_path / "shapes.json"
    path.write_text(json.dumps({"payload": json.dumps(read)}))
    out = tmp_path / "report.json"
    assert room_shape_report.main(["--read", str(path), "--out", str(out)]) == 1
    assert json.loads(out.read_text())["counts"]["block"] == 1
    assert room_shape_report.main(["--read", str(path), "--min-width-in", "3"]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"error": "no_project_document", "message": "x"}))
    assert room_shape_report.main(["--read", str(bad)]) == 2

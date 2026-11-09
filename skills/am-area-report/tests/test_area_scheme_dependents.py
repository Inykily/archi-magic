# -*- coding: utf-8 -*-
"""Tests for area_scheme_dependents.py (issue #197)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import area_scheme_dependents as asd  # noqa: E402


def test_cross_scheme_dependents_flagged_with_counts_per_scheme_and_level():
    schemes = [
        {
            "id": 10,
            "name": "Unused Scheme A",
            "dependents": [
                {"id": 101, "category": "Areas", "area_scheme_id": 10, "area_scheme_name": "Unused Scheme A", "level": "L1"},
                {"id": 201, "category": "Areas", "area_scheme_id": 20, "area_scheme_name": "Active Scheme B", "level": "L1"},
                {"id": 202, "category": "Areas", "area_scheme_id": 20, "area_scheme_name": "Active Scheme B", "level": "L2"},
                {"id": 301, "category": "Area Boundary Lines"},
            ],
        }
    ]
    res = asd.analyze_scheme_dependents(schemes)
    assert res["has_cross_scheme_risk"] is True
    sc = res["schemes"][0]
    assert sc["blocked_for_delete"] is True
    assert sc["own_areas_count"] == 1
    assert sc["cross_scheme_areas_count"] == 2
    assert sc["cross_by_scheme"] == {"Active Scheme B": 2}
    assert sc["cross_by_scheme_level"] == {"Active Scheme B": {"L1": 1, "L2": 1}}
    assert "Scheme 'Unused Scheme A' will take 2 area(s) of scheme 'Active Scheme B' with it" in sc["status_line"]


def test_clean_scheme_reports_positive_control_no_cross_scheme_areas():
    schemes = [
        {
            "id": 10,
            "name": "Rentable",
            "dependents": [
                {"id": 101, "category": "Areas", "area_scheme_id": 10, "area_scheme_name": "Rentable", "level": "L1"},
                {"id": 102, "category": "Areas", "area_scheme_id": 10, "area_scheme_name": "Rentable", "level": "L2"},
            ],
        }
    ]
    res = asd.analyze_scheme_dependents(schemes)
    assert res["has_cross_scheme_risk"] is False
    sc = res["schemes"][0]
    assert sc["blocked_for_delete"] is False
    assert sc["own_areas_count"] == 2
    assert sc["status_line"] == "No cross-scheme areas (scheme 'Rentable' has 2 own area(s))."


def test_point_in_area_loops_handles_interior_holes_with_even_odd_rule():
    outer = [(0, 0), (100, 0), (100, 100), (0, 100)]
    hole = [(30, 30), (70, 30), (70, 70), (30, 70)]
    loops = [outer, hole]

    # Point inside outer ring but outside hole -> covered (True)
    assert asd.point_in_area_loops((15, 15), loops) is True
    # Point inside the interior hole -> contained in 2 loops (even) -> NOT covered (False)
    assert asd.point_in_area_loops((50, 50), loops) is False
    # Point completely outside -> False
    assert asd.point_in_area_loops((150, 50), loops) is False


def test_export_restore_bundle_and_verify_guards():
    scheme = {
        "id": 10,
        "name": "Unused Scheme A",
        "dependents": [
            {
                "id": 201,
                "category": "Areas",
                "area_scheme_id": 20,
                "area_scheme_name": "Active Scheme B",
                "level": "Level 2",
                "point": [12.5, 34.0, 14.0],
                "area_ft2": 420.0,
                "perimeter_ft": 86.0,
                "workset": "Shared Views, Levels, Grids",
                "number": "204",
                "name": "Lab",
                "parameters": {"Department": "Science"},
                "tags": [{"owner_view_unique_id": "view-uid-2", "tag_type_id": 55, "head_position": [13.0, 34.0, 14.0], "has_leader": True}],
            }
        ],
    }
    bundle = asd.export_restore_bundle(scheme)
    assert bundle["area_count"] == 1
    expected = bundle["areas"]
    restored = [dict(expected[0])]
    other_before = [{"stable_key": "Level 1:5.000,5.000", "area_ft2": 100.0, "number": "101", "name": "Lobby", "workset": "W1", "parameters": {}}]
    other_after = [dict(other_before[0])]

    guards = asd.verify_restore_guards(expected, restored, other_before, other_after)
    assert guards["ok"] is True
    assert guards["self_test_ok"] is True
    assert guards["restore_diffs"] == []
    assert guards["other_areas_diffs"] == []

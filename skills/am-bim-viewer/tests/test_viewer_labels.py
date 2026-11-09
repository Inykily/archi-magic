# -*- coding: utf-8 -*-
"""Tests for viewer_labels.py (issue #199)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import viewer_labels as vl  # noqa: E402


ELEMENTS = [
    {
        "id": 1,
        "category": "Mass",
        "mesh": {"vertices": [0, 0, 0, 100, 80, 60], "indices": [0, 1, 0]},
    },
    {
        "id": 2,
        "category": "SiteContext",
        "mesh": {"vertices": [-2000, -2000, -50, 3000, 3000, 0], "indices": [0, 1, 0]},
    },
]


def test_bounds_for_categories_ignores_far_away_context():
    all_b = vl.bounds_for_categories(ELEMENTS)
    assert all_b["min"] == [-2000.0, -2000.0, -50.0]

    mass_b = vl.bounds_for_categories(ELEMENTS, ["Mass"])
    assert mass_b["min"] == [0.0, 0.0, 0.0]
    assert mass_b["max"] == [100.0, 80.0, 60.0]


def test_resolve_label_anchor_fixed_and_bbox_relative():
    fixed = {"text": "Main Entry", "position": [10.0, -5.0, 0.0], "offset": [0, 0, 2]}
    assert vl.resolve_label_anchor(fixed, ELEMENTS) == [10.0, -5.0, 2.0]

    # Relative to "Mass" top-center (0.5, 0.5, 1.0) + 5 ft Z offset
    rel = {"text": "Option 1 Tower", "category": "Mass", "rel": [0.5, 0.5, 1.0], "offset": [0, 0, 5]}
    assert vl.resolve_label_anchor(rel, ELEMENTS) == [50.0, 40.0, 65.0]


def test_format_pin_anchor_and_rhino_orbit_controls():
    pin = vl.format_pin_anchor([12.3456, -45.6789, 8.1], "North Entry")
    assert pin == {"text": "North Entry", "position": [12.35, -45.68, 8.1]}

    cfg = vl.rhino_orbit_controls_config()
    assert cfg["LEFT"] is None
    assert cfg["MIDDLE"] == "PAN"
    assert cfg["RIGHT"] == "ROTATE"

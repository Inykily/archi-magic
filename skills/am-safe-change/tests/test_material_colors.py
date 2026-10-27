# -*- coding: utf-8 -*-
"""Tests for scripts/lib/material_colors.py (issue #27).

Run either way:
    python -m pytest skills/am-safe-change/tests -q
    python skills/am-safe-change/tests/test_material_colors.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import material_colors as mc  # noqa: E402


def mat(i, name="M%d" % 1, shading=None, pattern=None, used=None):
    return {"id": i, "name": name, "shading": shading,
            "surface_pattern_id": 7 if pattern is not None else None,
            "surface_pattern_name": "Diagonal" if pattern is not None else None,
            "surface_pattern_color": pattern,
            "used_by_categories": used or []}


BASE = [mat(1, "Floor - Timber", [210, 180, 140], [90, 90, 90], ["Floors"]),
        mat(2, "Wall - Paint", [240, 240, 240], None, ["Walls"]),
        mat(3, "Glass", [180, 200, 210], [30, 30, 30], ["Curtain Panels", "Walls"])]


def req(items):
    return {"kind": "material-colors", "source": "am-safe-change", "items": items}


def test_contrast_ratios():
    # Black on white is the WCAG maximum, 21:1.
    assert mc.contrast_ratio([0, 0, 0], [255, 255, 255]) == 21.0
    # Same color against itself is 1:1.
    assert mc.contrast_ratio([120, 120, 120], [120, 120, 120]) == 1.0
    # Order does not matter.
    assert mc.contrast_ratio([255, 255, 255], [0, 0, 0]) == 21.0


def test_suggest_greys_stay_readable():
    greys = mc.suggest_greys(5, [0, 0, 0])
    assert len(greys) == 5
    assert greys[0]["hex"] == "#FFFFFF"
    for g in greys:
        # Every grey keeps black text at WCAG AA (4.5:1).
        assert g["text_contrast"] >= 4.5
    # The darkest grey is the darkest that still passes 4.5:1.
    assert greys[-1]["text_contrast"] >= 4.5
    darker = [greys[-1]["rgb"][0] - 1] * 3
    assert mc.contrast_ratio(darker, [0, 0, 0]) < 4.5
    # Greys run light to dark.
    levels = [g["rgb"][0] for g in greys]
    assert levels == sorted(levels, reverse=True)


def test_suggest_greys_pattern_ratio():
    greys = mc.suggest_greys(3, [200, 0, 0])
    for g in greys:
        assert g["pattern_contrast"] == round(mc.contrast_ratio(g["rgb"], [200, 0, 0]), 2)


def test_suggest_greys_bad_count():
    try:
        mc.suggest_greys(0)
    except ValueError as e:
        assert "at least 1" in str(e)
    else:
        raise AssertionError("count 0 must fail")


def test_compute_preview():
    p = mc.compute_preview(req([{"id": 1, "shading": [200, 170, 130]}]), BASE)
    assert p["kind"] == "change-preview"
    assert p["keyColumn"] == "ElementId"
    assert p["columns"] == ["ElementId", "Material", "Shading", "Surface pattern"]
    assert p["before"][0] == [1, "Floor - Timber", "rgb(210, 180, 140)", "rgb(90, 90, 90)"]
    assert p["after"][0] == [1, "Floor - Timber", "rgb(200, 170, 130)", "rgb(90, 90, 90)"]
    assert len(p["steps"]) == 1
    st = p["steps"][0]
    assert st["expect"] == {"shading": [210, 180, 140], "surface_pattern_color": [90, 90, 90]}
    assert st["expectAfter"] == {"shading": [200, 170, 130], "surface_pattern_color": [90, 90, 90]}
    # Expected dependents come from the read result.
    assert p["expected_dependent_categories"] == ["Floors", "Keynote Tags", "Legends"]
    assert p["blocked"] is False


def test_compute_pattern_only():
    p = mc.compute_preview(req([{"id": 1, "surface_pattern_color": [10, 10, 10]}]), BASE)
    assert p["after"][0][2] == "rgb(210, 180, 140)"  # shading unchanged
    assert p["after"][0][3] == "rgb(10, 10, 10)"
    assert p["steps"][0]["shading"] is None


def test_low_pattern_contrast_warns():
    # Pattern color almost the same as the new shading: hard to see.
    p = mc.compute_preview(req([{"id": 1, "shading": [95, 95, 95],
                                 "surface_pattern_color": [90, 90, 90]}]), BASE)
    assert len(p["warnings"]) == 1
    assert p["warnings"][0]["type"] == "low_pattern_contrast"
    assert p["warnings"][0]["blocking"] is False


def test_validate_rejects():
    # Wrong kind.
    _items, errs = mc.validate_request({"kind": "other", "items": []}, BASE)
    assert errs
    # Unknown material.
    _items, errs = mc.validate_request(req([{"id": 99, "shading": [1, 2, 3]}]), BASE)
    assert any("99" in e for e in errs)
    # RGB out of range.
    _items, errs = mc.validate_request(req([{"id": 1, "shading": [300, 0, 0]}]), BASE)
    assert errs
    # No change at all.
    _items, errs = mc.validate_request(req([{"id": 1, "shading": [210, 180, 140]}]), BASE)
    assert any("changes nothing" in e for e in errs)
    # Duplicate id.
    _items, errs = mc.validate_request(
        req([{"id": 1, "shading": [1, 2, 3]}, {"id": 1, "shading": [4, 5, 6]}]), BASE)
    assert any("twice" in e for e in errs)
    # Empty items.
    _items, errs = mc.validate_request(req([]), BASE)
    assert errs


def test_compare_matches_and_differs():
    p = mc.compute_preview(req([{"id": 1, "shading": [200, 170, 130]},
                                {"id": 2, "shading": [10, 20, 30]}]), BASE)
    actual = {1: {"shading": [200, 170, 130], "surface_pattern_color": [90, 90, 90]},
              2: {"shading": [10, 20, 30], "surface_pattern_color": None}}
    assert mc.compare(p, actual) == []
    actual[2]["shading"] = [11, 20, 30]
    diffs = mc.compare(p, actual)
    assert len(diffs) == 1
    assert "material 2" in diffs[0]
    # An element changed but not in the preview.
    actual[99] = {"shading": [1, 1, 1], "surface_pattern_color": None}
    assert len(mc.compare(p, actual)) == 2


def test_text_table():
    p = mc.compute_preview(req([{"id": 1, "shading": [200, 170, 130]}]), BASE)
    table = mc.text_table(p)
    assert "| 1 | Floor - Timber | rgb(210, 180, 140) -> rgb(200, 170, 130) |" in table
    assert "Changed: 1." in table


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))

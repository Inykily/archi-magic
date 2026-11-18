# -*- coding: utf-8 -*-
"""Tests for scripts/lib/section_marks.py and scripts/section_mark_plan.py (issue #257).

Run either way:
    python -m pytest skills/am-safe-change/tests -q
    python skills/am-safe-change/tests/test_section_marks.py
"""
import importlib.util
import io
import json
import math
import os
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import section_marks as sm  # noqa: E402

CLI = os.path.join(HERE, "..", "scripts", "section_mark_plan.py")


def close(a, b, tol=1e-9):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def test_look_follows_the_bar_side_not_the_order_of_the_ends():
    # A cut along x. The bar is drawn on the north side: look north,
    # whichever end the reviewer drew first (mirrored marks).
    assert close(sm.look_from_bar_side([0, 0], [10, 0], [5, 1]), [0, 1, 0])
    assert close(sm.look_from_bar_side([10, 0], [0, 0], [5, 1]), [0, 1, 0])
    assert close(sm.look_from_bar_side([0, 0], [10, 0], [2, -0.3]), [0, -1, 0])


def test_look_needs_a_point_off_the_line():
    with pytest.raises(ValueError):
        sm.look_from_bar_side([0, 0], [10, 0], [5, 0])
    with pytest.raises(ValueError):
        sm.look_from_bar_side([1, 1], [1, 1], [5, 5])


@pytest.mark.parametrize("deg", [0, 37, 90, 211])
def test_detail_box_frame_is_right_handed_and_looks_along_the_mark(deg):
    d = [math.cos(math.radians(deg)), math.sin(math.radians(deg))]
    start, end = [100.0, 50.0], [100.0 + 8 * d[0], 50.0 + 8 * d[1]]
    look = sm.look_from_bar_side(start, end, [start[0] - d[1], start[1] + d[0]])
    box = sm.detail_box(start, end, look, bottom_z=-1.0, top_z=11.0, depth=6.0, padding=1.0)
    assert close(cross(box["basis_x"], box["basis_y"]), box["basis_z"])
    assert close(box["basis_z"], look)
    assert close(box["min"], [-5.0, -1.0, 0.0]) and close(box["max"], [5.0, 11.0, 6.0])
    assert close(box["origin"], [100 + 4 * d[0], 50 + 4 * d[1], 0])
    # What Revit documents for CreateDetail: ViewDirection = -BasisZ.
    assert sm.view_direction_ok([-c for c in box["basis_z"]], look)
    assert not sm.view_direction_ok(box["basis_z"], look)


def test_detail_box_rejects_bad_input():
    with pytest.raises(ValueError):
        sm.detail_box([0, 0], [10, 0], [1, 0, 0], 0, 10, 5)      # look along the line
    with pytest.raises(ValueError):
        sm.detail_box([0, 0], [10, 0], [0, 1, 0], 10, 0, 5)      # top below bottom
    with pytest.raises(ValueError):
        sm.detail_box([0, 0], [10, 0], [0, 1, 0], 0, 10, 0)      # no depth


def marker(name, start, end, z=(0.0, 12.0)):
    return {"id": name, "name": name, "start": start, "end": end, "z_min": z[0], "z_max": z[1]}


def test_duplicates_within_tolerance_and_parallel():
    existing = [marker("Section 4", [0, 0.5], [10, 0.5]), marker("Section 9", [50, -5], [50, 5])]
    cuts = [{"name": "M1", "start": [0, 0], "end": [10, 0]},          # 0.5 ft from Section 4
            {"name": "M2", "start": [20, 0], "end": [30, 0]},         # far from all
            {"name": "M3", "start": [45, 0.2], "end": [55, 0.2]},     # crosses Section 9 at 90 deg
            {"name": "M4", "start": [20.3, 0.1], "end": [30.3, 0.1]}]  # repeats M2
    rows = sm.find_duplicates(cuts, existing, tolerance=1.0)
    assert [r["duplicate"] for r in rows] == [True, False, False, True]
    assert rows[0]["duplicate_of"] == "Section 4" and abs(rows[0]["distance"] - 0.5) < 1e-9
    assert rows[2]["nearest"] == "Section 9" and rows[2]["angle"] == pytest.approx(90)
    assert rows[3]["duplicate_of"] == "new cut M2"


def test_markers_at_level_keeps_only_cuts_through_that_level():
    found = sm.markers_at_level([marker("L1", [0, 0], [1, 0], (0, 12)),
                                 marker("L5", [0, 0], [1, 0], (60, 72))], z=4.0)
    assert [m["name"] for m in found] == ["L1"]


def test_cli_plan(capsys):
    tmp = tempfile.mkdtemp()

    def write(name, data):
        path = os.path.join(tmp, name)
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data))
        return path

    marks = write("marks.json", {"marks": [
        {"name": "M1", "start": [0, 0], "end": [10, 0], "bar_side": [5, 1]},
        {"name": "M2", "start": [20, 0], "end": [30, 0], "look": [0, -1]}]})
    markers = write("markers.json", {"result": {"markers": [marker("Section 4", [0, 0.5], [10, 0.5]),
                                                            marker("Upper", [20, 0], [30, 0], (60, 72))]}})
    spec = importlib.util.spec_from_file_location("section_mark_plan_cli", CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = os.path.join(tmp, "plan.json")
    code = mod.main(["plan", "--marks", marks, "--markers", markers, "--bottom-z", "-1",
                     "--top-z", "11", "--depth", "6", "--level-z", "4", "--out", out])
    text = capsys.readouterr().out
    assert code == 1
    assert "M1: DUPLICATE of Section 4" in text
    assert "M2: new, look (0.000, -1.000)" in text
    with io.open(out, encoding="utf-8") as f:
        plan = json.load(f)
    assert plan["checked_markers"] == 1  # the upper-level marker is left out
    assert plan["cuts"][0]["box"] is None and plan["cuts"][1]["box"]["basis_z"] == [0.0, -1.0, 0.0]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

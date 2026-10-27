# -*- coding: utf-8 -*-
"""Tests for scripts/lib/transforms.py.

Run either way:
    python -m pytest skills/am-safe-change/tests -q
    python skills/am-safe-change/tests/test_transforms.py
"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import transforms as tf  # noqa: E402


def req(items, **over):
    r = {"kind": "element-transforms", "source": "am-bim-viewer", "units": "ft", "items": items}
    r.update(over)
    return r


def item(i, move=(0, 0, 0), rz=0, pivot=(0, 0, 0), **extra):
    d = {"id": i, "name": "E%d" % i, "category": "Furniture", "move": list(move),
         "rotateZ": rz, "pivot": list(pivot)}
    d.update(extra)
    return d


def el(i, point=(10.0, 0.0, 0.0), rotation=0.0, kind="point", **extra):
    d = {"id": i, "exists": True, "name": "E%d" % i, "category": "Furniture",
         "kind": kind, "point": list(point) if point is not None else None, "rotation": rotation, "pinned": False,
         "groupId": 0, "hostId": 0, "hostCategory": "", "dependents": [],
         "levelId": 311, "isView": False, "viewSpecific": False}
    d.update(extra)
    return d


def types(p, blocking=None):
    return sorted(w["type"] for w in p["warnings"]
                  if blocking is None or w["blocking"] == blocking)


# ---------------------------------------------------------------- validation

def test_valid_request():
    items, errors = tf.validate_request(req([item(1, (2, 0, 0), 15, (1, 2, 0))]))
    assert errors == []
    assert items == [{"id": 1, "name": "E1", "category": "Furniture", "move": [2.0, 0.0, 0.0],
                      "rotateZ": 15.0, "pivot": [1.0, 2.0, 0.0], "otherAxes": []}]


def test_bad_kind():
    _i, errors = tf.validate_request(req([item(1)], kind="change-preview"))
    assert len(errors) == 1 and "kind" in errors[0]


def test_units_not_ft():
    _i, errors = tf.validate_request(req([item(1)], units="mm"))
    assert len(errors) == 1 and "units" in errors[0]


def test_missing_fields():
    no_move = item(1)
    del no_move["move"]
    no_rot = item(2)
    del no_rot["rotateZ"]
    no_pivot = item(3, rz=10)
    del no_pivot["pivot"]
    no_id = item(4)
    del no_id["id"]
    _i, errors = tf.validate_request(req([no_move, no_rot, no_pivot, no_id]))
    assert len(errors) == 4
    assert "move is missing" in errors[0]
    assert "rotateZ is missing" in errors[1]
    assert "pivot is missing" in errors[2]
    assert "id must be" in errors[3]


def test_pivot_optional_without_rotation():
    it = item(1, (1, 0, 0))
    del it["pivot"]
    items, errors = tf.validate_request(req([it]))
    assert errors == [] and items[0]["pivot"] is None


def test_empty_items_and_duplicates():
    assert tf.validate_request(req([]))[1] == ["items must be a non-empty list."]
    _i, errors = tf.validate_request(req([item(1), item(1)]))
    assert len(errors) == 1 and "twice" in errors[0]


def test_bad_vector():
    _i, errors = tf.validate_request(req([item(1, move=(1, 2))]))
    assert "move must be" in errors[0]


def test_compute_rejects_invalid_request():
    try:
        tf.compute_preview(req([item(1)], units="m"), [el(1)])
    except ValueError as e:
        assert "Request rejected" in str(e)
    else:
        raise AssertionError("invalid request was accepted")


# ---------------------------------------------------------------- math

def test_move_only():
    p, r = tf.after_state([1.0, 2.0, 3.0], 30.0, [2.0, -1.0, 0.5], 0, None)
    assert p == [3.0, 1.0, 3.5] and r == 30.0


def test_rotate_90_about_pivot_is_exact():
    # (10, 0) about (0, 0) by +90 (CCW) -> (0, 10), exactly.
    p, r = tf.after_state([10.0, 0.0, 4.0], 0.0, [0, 0, 0], 90, [0.0, 0.0, 0.0])
    assert p == [0.0, 10.0, 4.0]
    assert r == 90.0


def test_rotate_90_about_offset_pivot():
    # (3, 1) about (1, 1) by +90 -> (1, 3).
    p, _r = tf.after_state([3.0, 1.0, 0.0], 0.0, [0, 0, 0], 90, [1.0, 1.0, 0.0])
    assert p == [1.0, 3.0, 0.0]


def test_rotate_negative_and_180():
    p, r = tf.after_state([10.0, 0.0, 0.0], 0.0, [0, 0, 0], -90, [0.0, 0.0, 0.0])
    assert p == [0.0, -10.0, 0.0] and r == 270.0
    p, r = tf.after_state([10.0, 0.0, 0.0], 350.0, [0, 0, 0], 180, [0.0, 0.0, 0.0])
    assert p == [-10.0, 0.0, 0.0] and r == 170.0


def test_rotate_15_then_move():
    # Rotate first about the pivot, then move.
    p, r = tf.after_state([10.0, 0.0, 0.0], 350.0, [2.0, 0.0, 0.0], 15, [0.0, 0.0, 0.0])
    assert abs(p[0] - (10 * 0.9659258262890683 + 2)) < 1e-12
    assert abs(p[1] - 10 * 0.25881904510252074) < 1e-12
    assert p[2] == 0.0
    assert abs(r - 5.0) < 1e-9


def test_rotation_none_stays_none():
    _p, r = tf.after_state([1.0, 0.0, 0.0], None, [0, 0, 0], 45, [0.0, 0.0, 0.0])
    assert r is None


def test_angle_diff_wraps():
    assert tf.angle_diff(359.99999, 0.00001) < 1e-4
    assert tf.angle_diff(10, 350) == 20


# ---------------------------------------------------------------- warnings

def test_pinned_grouped_hosted_block():
    els = [el(1, pinned=True), el(2, groupId=900), el(3, hostId=77, hostCategory="Walls"),
           el(4, dependents=[5, 6])]
    p = tf.compute_preview(req([item(i, (2, 0, 0)) for i in (1, 2, 3, 4)]), els)
    assert p["blocked"] and p["steps"] == []
    assert types(p, True) == ["grouped", "hosted", "hosts_others", "pinned"]
    assert [w["row"] for w in p["warnings"]] == ["1", "2", "3", "4"]
    assert tf.decisions_needed(p) == {"pinned": ["1"], "grouped": ["2"],
                                      "hosted": ["3"], "hosts_others": ["4"]}


def test_accept_hosted_unblocks():
    els = [el(3, hostId=77, hostCategory="Walls"), el(4, dependents=[5])]
    p = tf.compute_preview(req([item(3, (2, 0, 0)), item(4, (2, 0, 0))]), els,
                           accept=["hosted", "hosts_others"])
    assert not p["blocked"]
    assert types(p, False) == ["hosted", "hosts_others"]
    assert [s["id"] for s in p["steps"]] == [3, 4]


def test_pinned_cannot_be_accepted_only_skipped():
    try:
        tf.compute_preview(req([item(1, (1, 0, 0))]), [el(1, pinned=True)], accept=["pinned"])
    except ValueError as e:
        assert "only skipped" in str(e)
    else:
        raise AssertionError("pinned was accepted")
    p = tf.compute_preview(req([item(1, (1, 0, 0)), item(2, (1, 0, 0))]),
                           [el(1, pinned=True), el(2)], skip_ids=[1])
    assert not p["blocked"] and [s["id"] for s in p["steps"]] == [2]
    assert p["after"][0] == p["before"][0]


def test_not_found_not_movable_non_vertical():
    els = [{"id": 1, "exists": False}, el(2, kind="none", point=None, rotation=None),
           el(3)]
    p = tf.compute_preview(req([item(1, (1, 0, 0)), item(2, (1, 0, 0)),
                                item(3, rz=10, rotateX=5)]), els)
    assert types(p, True) == ["non_vertical_axis", "not_found", "not_movable"]


def test_cross_level_is_flagged_not_blocking():
    p = tf.compute_preview(req([item(1, (0, 0, 10))]), [el(1)])
    assert not p["blocked"]
    assert types(p) == ["cross_level"]


# ---------------------------------------------------------------- preview shape

def test_preview_shape_deep_equality():
    els = [el(101, point=(10.0, 0.0, 0.0), rotation=0.0, name="Column A", category="Structural Columns"),
           el(102, point=(0.0, 0.0, 0.0), rotation=45.0, name="Desk", category="Furniture")]
    request = req([item(101, (2, 0, 0), 90, (0, 0, 0)), item(102, (0, 0, 0), 0, (0, 0, 0))])
    p = tf.compute_preview(request, els, "autodesk.unit.unit:millimeters-1.0.1")
    assert p == {
        "kind": "change-preview",
        "title": "Move or rotate 1 element(s)",
        "keyColumn": "ElementId",
        "columns": ["ElementId", "Name", "Category", "Location", "Rotation"],
        "changedColumns": ["Location", "Rotation"],
        "before": [
            [101, "Column A", "Structural Columns", "(10.000, 0.000, 0.000) ft = (3048, 0, 0) mm", "0.00 deg"],
            [102, "Desk", "Furniture", "(0.000, 0.000, 0.000) ft = (0, 0, 0) mm", "45.00 deg"],
        ],
        "after": [
            [101, "Column A", "Structural Columns", "(2.000, 10.000, 0.000) ft = (610, 3048, 0) mm", "90.00 deg"],
            [102, "Desk", "Furniture", "(0.000, 0.000, 0.000) ft = (0, 0, 0) mm", "45.00 deg"],
        ],
        "notes": [
            "1 of 2 elements move or rotate.",
            "Lengths are Revit internal feet. The project shows lengths in millimeters.",
            "Order: rotate about the pivot first (vertical axis, counter-clockwise positive), then move.",
            "Location is the location point, or the midpoint of the location line.",
        ],
        "warnings": [],
        "blocked": False,
        "params": {"source": "am-bim-viewer", "units": "ft", "skip": [], "accept": [],
                   "lengthUnit": "autodesk.unit.unit:millimeters-1.0.1"},
        "steps": [{"id": 101, "move": [2.0, 0.0, 0.0], "rotateZ": 90.0, "pivot": [0.0, 0.0, 0.0],
                   "kind": "point",
                   "expect": {"point": [10.0, 0.0, 0.0], "rotation": 0.0},
                   "expectAfter": {"point": [2.0, 10.0, 0.0], "rotation": 90.0}}],
        "expected_dependent_categories": ["Dimensions"],
    }


def test_compare_matches_and_differs():
    p = tf.compute_preview(req([item(1, (2, 0, 0), 15, (0, 0, 0))]), [el(1)])
    want = p["steps"][0]["expectAfter"]
    ok = {1: {"point": [want["point"][0] + 1e-9, want["point"][1], want["point"][2]],
              "rotation": want["rotation"] + 1e-7}}
    assert tf.compare(p, ok) == []
    bad = copy.deepcopy(ok)
    bad[1]["rotation"] = want["rotation"] + 1.0
    assert len(tf.compare(p, bad)) == 1
    assert len(tf.compare(p, {})) == 1


def test_unescape_read_result():
    data = {"result": {"escaped": True, "lengthUnit": "x", "elements": [
        dict(el(1), name="Caf\\u00e9", category="M\\u00f6bel")]}}
    els, unit = tf.load_read_result(data)
    assert els[0]["name"] == u"Café" and els[0]["category"] == u"Möbel" and unit == "x"


# ---------------------------------------------------------------- mutation

def _math_tests():
    return [test_rotate_90_about_pivot_is_exact, test_rotate_90_about_offset_pivot,
            test_rotate_negative_and_180, test_rotate_15_then_move]


def test_mutation_flipped_rotation_sign_goes_red():
    """Guard check: if rotate_xy turned clockwise, the math tests must fail."""
    original = tf.cos_sin

    def flipped(deg):
        c, s = original(deg)
        return c, -s
    tf.cos_sin = flipped
    try:
        caught = 0
        for t in _math_tests():
            try:
                t()
            except AssertionError:
                caught += 1
        assert caught == len(_math_tests()), "only %d of %d math tests went red" % (caught, len(_math_tests()))
    finally:
        tf.cos_sin = original
    for t in _math_tests():
        t()  # green again after restore


if __name__ == "__main__":
    names = sorted(n for n in dir() if n.startswith("test_"))
    failed = 0
    for n in names:
        try:
            globals()[n]()
            print("PASS %s" % n)
        except Exception as e:  # report every failure, then exit non-zero
            failed += 1
            print("FAIL %s: %s" % (n, e))
    print("%d passed, %d failed" % (len(names) - failed, failed))
    sys.exit(1 if failed else 0)

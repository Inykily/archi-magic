# -*- coding: utf-8 -*-
"""Tests for scripts/lib/reference_samples.py.

Run either way:
    python -m pytest skills/am-reference-samples/tests -q
    python skills/am-reference-samples/tests/test_reference_samples.py

Every test uses fixture data only. No Revit runs here: the live-Revit
run is explicitly not verified by this suite (see the skill).
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import reference_samples as rs  # noqa: E402


def model():
    return {
        "Line Styles": ["<Thin Lines>", "Wide Lines", "Dashed",
                        "<Sketch>", "White Style"],
        "Text": ["3/32in Arial", "1/4in Arial", "Title 2in"],
        "Dimensions": ["Linear 3/32in", "Angular"],
    }


def samples_thin_lines_fault():
    # The issue's first fault: the label names Wide Lines, but the
    # sample itself is drawn with <Thin Lines>.
    return [
        {"category": "Line Styles", "label": "Wide Lines",
         "sample_type": "<Thin Lines>"},
        {"category": "Line Styles", "label": "Dashed",
         "sample_type": "Dashed"},
    ]


def test_mismatch_reports_thin_lines_fault():
    cov = rs.check_coverage(model(), samples_thin_lines_fault())
    assert len(cov["mismatches"]) == 1
    fault = cov["mismatches"][0]
    assert fault["label"] == "Wide Lines"
    assert fault["sample_type"] == "<Thin Lines>"
    # Wide Lines has no sample of its own: the mismatch also leaves
    # it missing, since only <Thin Lines> is drawn.
    assert "Wide Lines" in cov["missing"]["Line Styles"]


def test_unknown_labels_name_types_not_in_model():
    samples = [
        {"category": "Line Styles", "label": "Gone Style",
         "sample_type": "Dashed"},
    ]
    cov = rs.check_coverage(model(), samples)
    assert len(cov["unknown_labels"]) == 1
    assert cov["unknown_labels"][0]["label"] == "Gone Style"


def test_missing_text_and_dimension_types():
    samples = [
        {"category": "Text", "label": "3/32in Arial",
         "sample_type": "3/32in Arial"},
    ]
    cov = rs.check_coverage(model(), samples)
    assert cov["missing"]["Text"] == ["1/4in Arial", "Title 2in"]
    assert cov["missing"]["Dimensions"] == ["Linear 3/32in", "Angular"]


def test_duplicates_reported_with_labels():
    samples = [
        {"category": "Text", "label": "3/32in Arial",
         "sample_type": "3/32in Arial"},
        {"category": "Text", "label": "3/32in Arial copy",
         "sample_type": "3/32in Arial"},
    ]
    cov = rs.check_coverage(model(), samples)
    assert len(cov["duplicates"]) == 1
    dup = cov["duplicates"][0]
    assert dup["sample_type"] == "3/32in Arial"
    assert dup["indices"] == [0, 1]


def test_clean_view_reports_clean():
    samples = []
    for cat, types in model().items():
        for t in types:
            samples.append({"category": cat, "label": t,
                            "sample_type": t})
    cov = rs.check_coverage(model(), samples)
    assert cov["clean"] is True
    assert cov["missing"] == {}
    assert cov["unknown_labels"] == []
    assert cov["duplicates"] == []
    assert cov["mismatches"] == []


def test_fix_samples_first_then_labels():
    cov = rs.check_coverage(model(), samples_thin_lines_fault())
    plan = rs.plan_fix(cov, {}, model(), {}, samples_thin_lines_fault())
    # The sample fix points at Wide Lines; the label fix follows it.
    assert plan["sample_ops"] == [
        {"index": 0, "category": "Line Styles", "label": "Wide Lines",
         "set_sample_to": "Wide Lines"}]
    assert plan["label_ops"] == [
        {"index": 0, "category": "Line Styles",
         "set_label_to": "Wide Lines"}]
    # The fixed fault row becomes the Wide Lines sample, so no
    # create op remains for Wide Lines. The fix orphans <Thin
    # Lines>: its only sample now draws Wide Lines, so the plan
    # creates a fresh <Thin Lines> sample. Other missing types still
    # need create ops.
    creates = [(c["category"], c["type"]) for c in plan["create_ops"]]
    assert ("Line Styles", "Wide Lines") not in creates
    assert ("Line Styles", "<Thin Lines>") in creates
    assert ("Line Styles", "<Sketch>") in creates
    assert ("Line Styles", "White Style") in creates


def test_fix_maps_label_through_rename_table():
    samples = [
        {"category": "Line Styles", "label": "Old Wide",
         "sample_type": "<Thin Lines>"},
    ]
    cov = rs.check_coverage(model(), samples)
    plan = rs.plan_fix(cov, {"Old Wide": "Wide Lines"}, model(), {}, samples)
    assert plan["sample_ops"][0]["set_sample_to"] == "Wide Lines"
    assert plan["label_ops"][0]["set_label_to"] == "Wide Lines"


def test_unfixable_label_never_gets_a_default_style():
    samples = [
        {"category": "Line Styles", "label": "Never Existed",
         "sample_type": "Dashed"},
    ]
    cov = rs.check_coverage(model(), samples)
    plan = rs.plan_fix(cov, {}, model(), {}, samples)
    assert plan["sample_ops"] == []
    assert plan["label_ops"] == []
    assert len(plan["unfixable"]) == 1
    assert plan["unfixable"][0]["label"] == "Never Existed"


def test_apply_plan_then_recheck_is_clean():
    samples = samples_thin_lines_fault()
    samples.append({"category": "Line Styles", "label": "<Thin Lines>",
                    "sample_type": "<Thin Lines>"})
    cov = rs.check_coverage(model(), samples)
    plan = rs.plan_fix(cov, {}, model(), {}, samples)
    fixed = rs.apply_plan(samples, plan)
    # After the fix, every remaining row matches its label, and
    # every missing type got a create op, so the re-check is clean.
    cov2 = rs.check_coverage(model(), fixed)
    assert cov2["mismatches"] == []
    assert cov2["duplicates"] == []
    assert cov2["unknown_labels"] == []
    assert cov2["missing"] == {}


def test_plan_is_idempotent():
    samples = samples_thin_lines_fault()
    cov = rs.check_coverage(model(), samples)
    plan = rs.plan_fix(cov, {}, model(), {}, samples)
    fixed = rs.apply_plan(samples, plan)
    plan2 = rs.plan_fix(rs.check_coverage(model(), fixed), {}, model(),
                        {}, fixed)
    assert plan2["sample_ops"] == []
    assert plan2["label_ops"] == []
    assert plan2["create_ops"] == []
    assert plan2["remove_ops"] == []
    # The unfixable list is not an op: it persists by design, since
    # the label still names a type that does not exist.


def test_duplicate_fix_keeps_first_row_only():
    samples = [
        {"category": "Text", "label": "3/32in Arial",
         "sample_type": "3/32in Arial"},
        {"category": "Text", "label": "3/32in Arial",
         "sample_type": "3/32in Arial"},
    ]
    cov = rs.check_coverage(model(), samples)
    plan = rs.plan_fix(cov, {}, model(), {}, samples)
    assert plan["remove_ops"] == [
        {"index": 1, "category": "Text",
         "sample_type": "3/32in Arial"}]
    fixed = rs.apply_plan(samples, plan)
    # The duplicate row is gone; the first row stays, plus create
    # ops for the missing types.
    assert sum(1 for r in fixed
               if r["sample_type"] == "3/32in Arial") == 1


def test_no_sample_reasons():
    assert rs.no_sample_reason("Spot Elevation", "Any") is not None
    assert rs.no_sample_reason("Spot Slope", "Any") is not None
    assert rs.no_sample_reason("Line Styles", "<Sketch>") is not None
    assert rs.no_sample_reason("Line Styles",
                               "<Area Boundary>") is not None
    assert rs.no_sample_reason("Line Styles",
                               "<Invisible lines>") is not None
    assert rs.no_sample_reason("Fill Patterns", "Diagonal",
                               has_fill_type=False) is not None
    assert rs.no_sample_reason("Fill Patterns", "Diagonal",
                               has_fill_type=True) is None
    assert rs.no_sample_reason("Line Styles", "White Style",
                               is_white=True) is not None
    assert rs.no_sample_reason("Line Styles", "Dashed") is None
    assert rs.no_sample_reason("Text", "3/32in Arial") is None


def test_missing_no_sample_type_becomes_text_row_not_create():
    cov = rs.check_coverage(model(), [])
    no_sample = {"Line Styles": {
        "<Sketch>": "cannot be set on a detail line"}}
    plan = rs.plan_fix(cov, {}, model(), no_sample, [])
    texts = [(r["category"], r["type"]) for r in plan["text_rows"]]
    assert ("Line Styles", "<Sketch>") in texts
    creates = [(c["category"], c["type"]) for c in plan["create_ops"]]
    assert ("Line Styles", "<Sketch>") not in creates


def test_layout_uses_real_box_height_and_header():
    # The issue's fault: a 3/32in note box is about 1.25 ft tall at
    # 1/4in = 1ft, so a smaller pitch overlaps labels.
    rows = [{"height_ft": 1.25, "gap_ft": 0.25},
            {"height_ft": 1.25, "gap_ft": 0.25}]
    tops = rs.layout_rows(10.0, rows)
    assert tops == [9.75, 8.25]
    boxes = [(tops[i] - rows[i]["height_ft"], tops[i])
             for i in range(2)]
    assert rs.find_overlaps(boxes) == []


def test_layout_twice_gives_same_result():
    rows = [{"height_ft": 1.25, "gap_ft": 0.25},
            {"height_ft": 0.5, "gap_ft": 0.25}]
    first = rs.layout_rows(10.0, rows)
    second = rs.layout_rows(10.0, rows)
    assert first == second
    # Moving the header moves every row by the same delta: the
    # layout is header-relative, never fixed-offset.
    moved = rs.layout_rows(12.0, rows)
    assert [m - f for m, f in zip(moved, first)] == [2.0, 2.0]


def test_overlap_check_finds_touching_and_overlapping():
    assert rs.find_overlaps([(0.0, 1.0), (0.5, 1.5)]) == [(0, 1)]
    # Touching at an edge is not an overlap.
    assert rs.find_overlaps([(0.0, 1.0), (1.0, 2.0)]) == []
    assert rs.find_overlaps([(0.0, 1.0), (2.0, 3.0)]) == []


def test_headers_dedupe_instead_of_growing():
    assert rs.dedupe_headers(["A", "A", "B", "A"]) == ["A", "B"]
    assert rs.dedupe_headers([]) == []


def test_size_spread_and_scale():
    spread = rs.size_spread([0.09375, 2.0])
    assert spread["min"] == 0.09375
    assert spread["max"] == 2.0
    assert abs(spread["ratio"] - 2.0 / 0.09375) < 1e-9
    assert rs.size_spread([]) == {"min": None, "max": None,
                                  "ratio": None}
    # A 2 ft sample prints at 2 in when the scale is 1 in = 1 ft.
    assert rs.scale_for_print_size(2.0, 2.0) == 12.0
    with pytest.raises(ValueError):
        rs.scale_for_print_size(2.0, 0)


def test_snapshot_title_carries_date():
    title = rs.snapshot_title("Parameters", "2026-11-04")
    assert title == "Parameters (snapshot 2026-11-04)"


def test_cli_reports_fault_and_plan(tmp_path):
    import json
    data = {"model_types": model(),
            "samples": samples_thin_lines_fault()}
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(data))
    cli = os.path.join(HERE, "..", "scripts", "check_samples.py")
    out = subprocess.check_output(
        [sys.executable, cli, str(path)]).decode("utf-8")
    assert "MISMATCH" in out
    assert "Wide Lines" in out
    assert "SET SAMPLE" in out

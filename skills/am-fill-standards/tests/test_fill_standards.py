# -*- coding: utf-8 -*-
"""Tests for scripts/lib/fill_standards.py and scripts/fill_report.py.

Run either way:
    python -m pytest skills/am-fill-standards/tests -q
    python skills/am-fill-standards/tests/test_fill_standards.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import fill_standards as fs  # noqa: E402
import fill_report as fr  # noqa: E402


def typ(i, name, masking, fg=7, bg=-1, drawing=0, reference=0):
    """One read-result filled region type."""
    def entry(pid):
        if pid <= 0:
            return {"pattern": "<none>", "pattern_id": -1, "color": None}
        return {"pattern": "Solid fill", "pattern_id": pid,
                "color": {"r": 0, "g": 0, "b": 0}}
    return {"id": i, "name": name, "masking": masking, "fg": entry(fg),
            "bg": entry(bg), "line_weight": 1,
            "drawing_uses": drawing, "reference_uses": reference}


def read_result(types=(), patterns=(), swatches=(), labels=(), ref=None):
    return {"model": "Test", "revit_year": "2026",
            "timestamp": "2026-11-04T00:00:00", "path": "",
            "reference_view": ref, "drafting_views": [],
            "types": list(types), "patterns": list(patterns),
            "swatches": list(swatches), "labels": list(labels)}


def test_suffix_status():
    assert fs.suffix_status("HATCH_OPQ", True) == "ok"
    assert fs.suffix_status("HATCH_OPQ", False) == "mismatch"
    assert fs.suffix_status("HATCH_TRN", False) == "ok"
    assert fs.suffix_status("HATCH_TRN", True) == "mismatch"
    assert fs.suffix_status("HATCH_OPQ", None) == "unverified"
    assert fs.suffix_status("HATCH", True) is None
    assert fs.suffix_status("HATCH", False) is None


def test_typo_flags():
    assert fs.typo_flags("HATCH  X") == ["double space"]
    assert fs.typo_flags("HATCH__X") == ["double underscore"]
    assert fs.typo_flags("HATCH 2") == ["trailing number"]
    assert fs.typo_flags("HATCH_2") == ["trailing number"]
    assert fs.typo_flags(" HATCH") == ["leading/trailing space"]
    assert fs.typo_flags("HATCH-X") == []
    assert fs.typo_flags("HATCH 12") == ["trailing number"]


def test_check_type():
    assert fs.check_type("SOLID_OPQ", False) == ["OPQ name but Masking off"]
    assert fs.check_type("SOLID_TRN", True) == ["TRN name but Masking on"]
    assert fs.check_type("SOLID_OPQ", None) == [
        "suffix present but Masking unknown"]
    assert fs.check_type("SOLID  2", True) == [
        "double space", "trailing number"]
    assert fs.check_type("SOLID_OPQ", True) == []


def test_split_label():
    assert fs.split_label("HATCH-DRFT-X") == ("HATCH", "DRFT-X")
    assert fs.split_label("SOLID_OPQ_GREY") == ("SOLID", "OPQ_GREY")
    assert fs.split_label("_OPQ_GREY") == ("OPQ", "GREY")
    assert fs.split_label("SOLID") == ("SOLID", "")
    assert fs.label_text("HATCH-DRFT-X") == "HATCH\nDRFT-X"
    assert fs.label_text("SOLID") == "SOLID"


def test_pair_labels():
    labels = [{"id": 1, "cx": 0.0, "cy": 0.0},
              {"id": 2, "cx": 9.25, "cy": 0.0},
              {"id": 3, "cx": None, "cy": None}]
    swatches = [{"id": 11, "cx": 0.1, "cy": 0.0},
                {"id": 12, "cx": 9.0, "cy": 0.0},
                {"id": 13, "cx": 9.5, "cy": 0.0}]
    pairs, unpaired = fs.pair_labels(labels, swatches)
    assert pairs[1] == 11
    # Label 2 sits between swatches 12 and 13: second is not much
    # farther, so the guard refuses the pair.
    assert pairs[2] is None
    assert pairs[3] is None
    assert unpaired == [2, 3]
    # One swatch only: no second to compare, so the pair holds.
    pairs, unpaired = fs.pair_labels(labels[:1], swatches[:1])
    assert pairs == {1: 11}
    assert unpaired == []


def test_build_rename_table():
    rows = [{"id": 1, "name": "OLD-A"}, {"id": 2, "name": "OLD-B"},
            {"id": 3, "name": "KEEP"}]
    table, errors = fs.build_rename_table(rows, {"OLD-A": "NEW-A",
                                                 "OLD-B": "OLD-B"})
    assert table == [{"id": 1, "old": "OLD-A", "new": "NEW-A"}]
    assert errors == []
    table, errors = fs.build_rename_table(rows, {"NOPE": "NEW-X"})
    assert table == []
    assert errors == ["unknown type: 'NOPE'"]
    table, errors = fs.build_rename_table(rows, {"OLD-A": " "})
    assert errors == ["empty new name for 'OLD-A'"]
    table, errors = fs.build_rename_table(rows, {"OLD-A": "NEW-X",
                                                 "OLD-B": "NEW-X"})
    assert "two types map to 'NEW-X': 'OLD-A' and 'OLD-B'" in errors
    table, errors = fs.build_rename_table(rows, {"OLD-A": "KEEP"})
    assert "new name 'KEEP' collides with existing type" in errors
    # Renaming away frees the name: a swap is allowed.
    table, errors = fs.build_rename_table(rows, {"OLD-A": "OLD-B",
                                                 "OLD-B": "OLD-A"})
    assert errors == []
    assert len(table) == 2


def test_classify_use():
    assert fs.classify_use(3, 1) == "drawings"
    assert fs.classify_use(0, 2) == "reference only"
    assert fs.classify_use(0, 0) == "unused"


def test_pattern_usage():
    patterns = [{"id": 7, "name": "Solid fill", "target": "Drafting"}]
    types = [typ(1, "A", True, fg=7), typ(2, "B", False, fg=-1, bg=7)]
    usage = fs.pattern_usage(patterns, types)
    assert usage[7]["fg"] == ["A"]
    assert usage[7]["bg"] == ["B"]


def test_unescape():
    assert fs.unescape("45\\u00b0 hatch") == "45\xb0 hatch"
    assert fs.unescape("back\\\\slash") == "back\\slash"
    assert fs.unescape("plain") == "plain"


def test_sync_plan():
    types = [typ(1, "HATCH-A", True, drawing=2),
             typ(2, "HATCH-B", False, drawing=0, reference=1),
             typ(3, "HATCH-C", True, drawing=1)]
    swatches = [{"id": 11, "type_id": 1, "type_name": "HATCH-A"},
                {"id": 12, "type_id": 2, "type_name": "HATCH-B"}]
    labels = [{"id": 21, "text": "WRONG", "cx": 0.0, "cy": 0.0},
              {"id": 22, "text": "HATCH\nB", "cx": 5.0, "cy": 0.0},
              {"id": 23, "text": "ORPHAN", "cx": 9.0, "cy": 9.0}]
    pairs = {21: 11, 22: 12, 23: None}
    plan = fs.sync_plan(types, swatches, labels, pairs)
    assert plan["missing"] == [{"id": 3, "name": "HATCH-C",
                                "drawing_uses": 1}]
    assert plan["stale"] == [{"id": 12, "type_id": 2,
                              "type_name": "HATCH-B"}]
    assert [f["label_id"] for f in plan["label_fixes"]] == [21]
    assert plan["label_fixes"][0]["expected"] == "HATCH\nA"
    assert plan["unpaired_labels"] == [23]


def test_report_counts_and_flags():
    types = [typ(1, "SOLID_OPQ", False, drawing=3),
             typ(2, "SOLID  2", True, reference=1),
             typ(3, "PLAIN", True)]
    rep = fs.report(read_result(types=types))
    assert rep["counts"] == {"types": 3, "drawings": 1,
                             "reference_only": 1, "unused": 1,
                             "flagged": 2, "patterns": 0}
    assert rep["rows"][0]["flags"] == ["OPQ name but Masking off"]
    assert rep["rows"][0]["used"] == "drawings"
    assert rep["rows"][1]["flags"] == ["double space", "trailing number"]
    assert rep["rows"][2]["flags"] == []


def test_report_reference_section():
    types = [typ(1, "HATCH-A", True, drawing=2),
             typ(2, "HATCH-B", False, drawing=1)]
    swatches = [{"id": 11, "type_id": 1, "type_name": "HATCH-A",
                 "cx": 0.0, "cy": 0.0}]
    labels = [{"id": 21, "text": "HATCH\nA", "cx": 0.1, "cy": 0.0,
               "text_type_id": 5}]
    rep = fs.report(read_result(types=types, swatches=swatches,
                                labels=labels))
    ref = rep["reference"]
    assert ref["swatches"] == 1
    assert ref["labels"] == 1
    assert [m["name"] for m in ref["missing"]] == ["HATCH-B"]
    assert ref["stale"] == []
    # The label already reads "HATCH" / "A" on two lines, so no rewrite.
    assert ref["label_fixes"] == []
    # A one-line label with the same words still needs the two-line form.
    labels = [{"id": 21, "text": "HATCH A", "cx": 0.1, "cy": 0.0,
               "text_type_id": 5}]
    rep = fs.report(read_result(types=types, swatches=swatches,
                                labels=labels))
    assert [f["label_id"] for f in
            rep["reference"]["label_fixes"]] == [21]


def test_render_table():
    types = [typ(1, "SOLID_OPQ", False, drawing=3)]
    rep = fs.report(read_result(types=types))
    text = fs.render_table(rep)
    assert "Filled region types: 1 total, 1 in drawings" in text
    assert "SOLID_OPQ" in text
    assert "OPQ name but Masking off" in text
    empty = fs.render_table(fs.report(read_result()))
    assert "No filled region types in this model." in empty


def test_fill_report_cli(tmp_path):
    read_path = tmp_path / "read.json"
    out_path = tmp_path / "report.json"
    read_path.write_text(json.dumps(read_result(
        types=[typ(1, "SOLID_OPQ", False, drawing=3)])))
    assert fr.main(["--read", str(read_path), "--out", str(out_path)]) == 0
    rep = json.loads(out_path.read_text())
    assert rep["counts"]["types"] == 1
    assert rep["rows"][0]["flags"] == ["OPQ name but Masking off"]
    # A read result that holds an error is exit 2, not a report.
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({"error": "no_project_document"}))
    assert fr.main(["--read", str(bad_path),
                    "--out", str(out_path)]) == 2
    assert fr.main(["--read", str(tmp_path / "missing.json"),
                    "--out", str(out_path)]) == 2

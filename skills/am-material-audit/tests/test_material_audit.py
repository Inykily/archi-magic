# -*- coding: utf-8 -*-
"""Tests for scripts/lib/material_audit.py and scripts/audit_report.py.

Run either way:
    python -m pytest skills/am-material-audit/tests -q
    python skills/am-material-audit/tests/test_material_audit.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import material_audit as ma  # noqa: E402
import audit_report as ar  # noqa: E402


def rgb(r, g, b):
    return {"r": r, "g": g, "b": b}


def mat(i, name, shading, fg=None, bg=None, cut_fg=None, cut_bg=None):
    """One read-result material. fg/bg are (pattern, color) pairs or None."""
    def entry(pair):
        if pair is None:
            return {"pattern": "<none>", "pattern_id": -1, "color": None}
        return {"pattern": pair[0], "pattern_id": 7, "color": pair[1]}
    return {"id": i, "name": name, "shading": shading,
            "shading_from_render_appearance": False, "transparency": 0,
            "surface_foreground": entry(fg), "surface_background": entry(bg),
            "cut_foreground": entry(cut_fg) if cut_fg else None,
            "cut_background": entry(cut_bg) if cut_bg else None}


def read_result(materials, used_type=(), used_family=()):
    return {"prefix": "Floor Finish", "model": "Test", "revit_year": "2026",
            "timestamp": "2026-10-27T00:00:00", "path": "", "matched": len(materials),
            "materials": materials,
            "used_in_type_structure": list(used_type),
            "used_in_family": list(used_family),
            "type_structure_checked": {"floor_types": 2, "wall_types": 1,
                                       "roof_types": 0, "ceiling_types": 0,
                                       "family_symbols": 3},
            "not_checked": ["linked models"]}


def test_rgb_text():
    assert ma.rgb_text(rgb(128, 64, 32)) == "128, 64, 32"
    assert ma.rgb_text(rgb(0, 0, 0)) == "0, 0, 0"
    assert ma.rgb_text(None) == "—"


def test_color_distance():
    assert ma.color_distance(rgb(10, 20, 30), rgb(10, 20, 30)) == 0.0
    assert ma.color_distance(rgb(0, 0, 0), rgb(255, 255, 255)) > 441.0
    assert ma.color_distance(rgb(0, 0, 0), rgb(255, 255, 255)) < 442.0
    assert ma.color_distance(None, rgb(1, 2, 3)) is None
    assert ma.color_distance(rgb(1, 2, 3), None) is None


def test_low_contrast_boundary():
    # 30 apart on one channel is below the 32 threshold; 32 apart is not.
    assert ma.is_low_contrast(rgb(100, 100, 100), rgb(130, 100, 100))
    assert not ma.is_low_contrast(rgb(100, 100, 100), rgb(132, 100, 100))
    assert not ma.is_low_contrast(rgb(100, 100, 100), None)
    assert not ma.is_low_contrast(None, rgb(100, 100, 100))


def test_duplicates_same_colors():
    a = mat(1, "Floor Finish - A", rgb(200, 100, 50),
            ("Solid fill", rgb(255, 255, 255)), ("Solid fill", rgb(0, 0, 0)))
    b = mat(2, "Floor Finish - B", rgb(200, 100, 50),
            ("Solid fill", rgb(255, 255, 255)), ("Solid fill", rgb(0, 0, 0)))
    groups = ma.find_duplicates([a, b])
    assert len(groups) == 1 and len(groups[0]) == 2


def test_duplicates_differ_by_shading_only():
    a = mat(1, "Floor Finish - A", rgb(200, 100, 50),
            ("Solid fill", rgb(255, 255, 255)), ("Solid fill", rgb(0, 0, 0)))
    b = mat(2, "Floor Finish - B", rgb(201, 100, 50),
            ("Solid fill", rgb(255, 255, 255)), ("Solid fill", rgb(0, 0, 0)))
    assert ma.find_duplicates([a, b]) == []


def test_duplicates_ignore_pattern_name():
    # Same colors, different pattern names: still duplicates by the rule.
    a = mat(1, "Floor Finish - A", rgb(200, 100, 50),
            ("Solid fill", rgb(255, 255, 255)), ("Solid fill", rgb(0, 0, 0)))
    b = mat(2, "Floor Finish - B", rgb(200, 100, 50),
            ("Diagonal", rgb(255, 255, 255)), ("Solid fill", rgb(0, 0, 0)))
    assert len(ma.find_duplicates([a, b])) == 1


def test_duplicates_skip_no_shading():
    a = mat(1, "Floor Finish - A", None)
    b = mat(2, "Floor Finish - B", None)
    assert ma.find_duplicates([a, b]) == []


def test_duplicates_three_in_one_group():
    ms = [mat(i, "Floor Finish - %d" % i, rgb(10, 20, 30)) for i in (1, 2, 3)]
    groups = ma.find_duplicates(ms)
    assert len(groups) == 1 and len(groups[0]) == 3


def test_audit_unused_scoped():
    a = mat(1, "Floor Finish - Oak", rgb(200, 100, 50))
    b = mat(2, "Floor Finish - Pine", rgb(190, 90, 40))
    c = mat(3, "Floor Finish - Tile", rgb(180, 80, 30))
    result = ma.audit(read_result([a, b, c], used_type=[1], used_family=[2]))
    rows = dict((r["id"], r) for r in result["rows"])
    assert rows[1]["used"] == "type structure"
    assert rows[2]["used"] == "family"
    assert rows[3]["used"] == "unused (scoped check)"
    assert result["unused"] == ["Floor Finish - Tile"]
    assert result["counts"] == {"matched": 3, "used": 2, "unused": 1,
                                "duplicate_groups": 0, "low_contrast": 0}
    assert result["not_checked"] == ["linked models"]


def test_audit_flags_duplicates_and_contrast():
    a = mat(1, "Floor Finish - A", rgb(200, 100, 50),
            ("Solid fill", rgb(250, 250, 250)), ("Solid fill", rgb(240, 240, 240)))
    b = mat(2, "Floor Finish - B", rgb(200, 100, 50),
            ("Solid fill", rgb(250, 250, 250)), ("Solid fill", rgb(240, 240, 240)))
    result = ma.audit(read_result([a, b]))
    rows = dict((r["id"], r) for r in result["rows"])
    assert rows[1]["duplicate_group"] == 1
    assert rows[2]["duplicate_group"] == 1
    assert rows[1]["low_contrast"] and rows[2]["low_contrast"]
    assert result["duplicates"] == [["Floor Finish - A", "Floor Finish - B"]]
    assert result["low_contrast"] == ["Floor Finish - A", "Floor Finish - B"]


def test_audit_cut_pattern_kept_only_when_present():
    a = mat(1, "Floor Finish - A", rgb(200, 100, 50),
            cut_fg=("Solid fill", rgb(10, 10, 10)))
    result = ma.audit(read_result([a]))
    row = result["rows"][0]
    assert row["cut_foreground"] == {"pattern": "Solid fill", "color": "10, 10, 10"}
    assert row["cut_background"] is None


def test_audit_empty():
    result = ma.audit(read_result([]))
    assert result["counts"]["matched"] == 0
    assert result["unused"] == []
    assert "Not checked" not in ma.render_table(result)
    assert "No materials start with this prefix." in ma.render_table(result)


def test_render_table_shows_rgb_not_hex():
    a = mat(1, "Floor Finish - Oak", rgb(200, 100, 50),
            ("Solid fill", rgb(255, 255, 255)), ("Solid fill", rgb(0, 0, 0)))
    result = ma.audit(read_result([a]))
    table = ma.render_table(result)
    assert "200, 100, 50" in table
    assert "255, 255, 255" in table
    assert "0, 0, 0" in table
    assert "c86432" not in table.lower()
    assert "Floor Finish - Oak" in table
    assert "unused (scoped check)" in table
    assert "Not checked by the scoped unused check" in table


def test_unescape_round_trip():
    escaped = {"escaped": True, "materials": [
        {"id": 1, "name": "Caf\\u00e9 \\\\u00e9 Floor", "shading": rgb(1, 2, 3),
         "shading_from_render_appearance": False, "transparency": 0,
         "surface_foreground": {"pattern": "<none>", "pattern_id": -1, "color": None},
         "surface_background": {"pattern": "<none>", "pattern_id": -1, "color": None},
         "cut_foreground": None, "cut_background": None}]}
    materials, _ = ma.load_read_result(escaped)
    assert materials[0]["name"] == u"Café \\u00e9 Floor"


def test_load_read_result_unwraps_run_json():
    inner = read_result([mat(1, "Floor Finish - Oak", rgb(1, 2, 3))])
    materials, _ = ma.load_read_result({"result": inner})
    assert [m["name"] for m in materials] == ["Floor Finish - Oak"]


def test_cli_writes_audit_json(tmp_path):
    read_path = tmp_path / "read.json"
    out_path = tmp_path / "audit.json"
    a = mat(1, "Floor Finish - Oak", rgb(200, 100, 50))
    read_path.write_text(json.dumps(read_result([a])), encoding="utf-8")
    assert ar.main(["--read", str(read_path), "--out", str(out_path)]) == 0
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["counts"]["matched"] == 1
    assert saved["unused"] == ["Floor Finish - Oak"]


def test_cli_bad_input(tmp_path):
    missing = tmp_path / "nope.json"
    assert ar.main(["--read", str(missing)]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text('{"no": "materials here"}', encoding="utf-8")
    assert ar.main(["--read", str(bad)]) == 2


if __name__ == "__main__":
    names = sorted(n for n in dir() if n.startswith("test_"))
    failed = 0
    for n in names:
        try:
            import inspect
            fn = globals()[n]
            if "tmp_path" in inspect.signature(fn).parameters:
                import tempfile
                import pathlib
                with tempfile.TemporaryDirectory() as d:
                    fn(pathlib.Path(d))
            else:
                fn()
            print("PASS %s" % n)
        except Exception as e:  # report every failure, then exit non-zero
            failed += 1
            print("FAIL %s: %s" % (n, e))
    print("%d passed, %d failed" % (len(names) - failed, failed))
    sys.exit(1 if failed else 0)

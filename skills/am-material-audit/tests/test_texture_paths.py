# -*- coding: utf-8 -*-
"""Tests for scripts/lib/texture_paths.py and scripts/texture_report.py.

Run either way:
    python -m pytest skills/am-material-audit/tests/test_texture_paths.py -q
    python skills/am-material-audit/tests/test_texture_paths.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import texture_paths as tp  # noqa: E402
import texture_report as tr  # noqa: E402


def fake_exists(existing):
    """An os.path.isfile stand-in backed by a set of normalized paths."""
    existing = set(tp.normalize_path(p) for p in existing)
    return lambda p: tp.normalize_path(p) in existing


def slot(slot, path):
    return {"slot": slot, "path": path}


def material(i, name, asset_id, slots, unreadable=False):
    return {"id": i, "name": name, "asset_id": asset_id,
            "asset_name": name + " asset", "asset_unreadable": unreadable,
            "slots": slots}


def read_result(materials):
    return {"prefix": "", "model": "Test", "revit_year": "2026",
            "timestamp": "2026-11-04T00:00:00", "path": "", "matched": len(materials),
            "materials": materials, "notes": ["test notes"]}


def test_split_candidates():
    assert tp.split_candidates(None) == []
    assert tp.split_candidates("") == []
    assert tp.split_candidates("a.jpg") == ["a.jpg"]
    assert tp.split_candidates("a.jpg|b.jpg") == ["a.jpg", "b.jpg"]
    assert tp.split_candidates("a.jpg||b.jpg") == ["a.jpg", "b.jpg"]
    assert tp.split_candidates("  a.jpg | b.jpg  ") == ["a.jpg", "b.jpg"]


def test_normalize_and_basename():
    assert tp.normalize_path("C:/tex/oak.jpg") == "C:\\tex\\oak.jpg"
    assert tp.normalize_path("  C:\\tex\\oak.jpg ") == "C:\\tex\\oak.jpg"
    assert tp.basename_of("C:/tex/oak.jpg") == "oak.jpg"
    assert tp.basename_of("oak.jpg") == "oak.jpg"
    assert tp.basename_of("\\\\server\\share\\oak.jpg") == "oak.jpg"


def test_classify_ok_exact_file():
    exists = fake_exists(["C:\\tex\\oak.jpg"])
    assert tp.classify_path("C:\\tex\\oak.jpg", exists, set()) == "ok"


def test_classify_ok_mixed_slashes():
    exists = fake_exists(["C:\\tex\\oak.jpg"])
    assert tp.classify_path("C:/tex/oak.jpg", exists, set()) == "ok"


def test_classify_ok_in_library_other_program_files_home():
    # Stored under (x86), installed under plain Program Files: Revit
    # finds it by file name alone, so it is not missing.
    exists = fake_exists([])
    lib = set(["oak.jpg"])
    stored = ("C:\\Program Files (x86)\\Common Files\\Autodesk Shared\\"
              "Materials\\Textures\\oak.jpg")
    assert tp.classify_path(stored, exists, lib) == "ok_in_autodesk_library"


def test_classify_ok_in_library_bare_name():
    exists = fake_exists([])
    assert tp.classify_path("oak.jpg", exists, set(["oak.jpg"])) == \
        "ok_in_autodesk_library"


def test_classify_library_match_is_case_insensitive():
    exists = fake_exists([])
    assert tp.classify_path("C:\\tex\\Oak.JPG", exists, set(["oak.jpg"])) == \
        "ok_in_autodesk_library"


def test_classify_file_not_found():
    exists = fake_exists([])
    assert tp.classify_path("C:\\tex\\gone.jpg", exists, set()) == \
        "file_not_found"
    assert tp.classify_path("gone.jpg", exists, set(["other.jpg"])) == \
        "file_not_found"


def test_classify_empty_path():
    exists = fake_exists([])
    assert tp.classify_path("", exists, set()) == "empty_path"
    assert tp.classify_path(None, exists, set()) == "empty_path"
    assert tp.classify_path("   ", exists, set()) == "empty_path"


def test_classify_pipe_candidates_first_missing_second_ok():
    exists = fake_exists(["D:\\acc\\oak.jpg"])
    raw = "C:\\old\\oak.jpg|D:\\acc\\oak.jpg"
    assert tp.classify_path(raw, exists, set()) == "ok"


def test_classify_pipe_candidates_all_missing():
    exists = fake_exists([])
    raw = "C:\\old\\oak.jpg|D:\\acc\\oak.jpg"
    assert tp.classify_path(raw, exists, set()) == "file_not_found"


def test_classify_pipe_candidates_library_fallback():
    exists = fake_exists([])
    raw = "C:\\old\\oak.jpg|oak.jpg"
    assert tp.classify_path(raw, exists, set(["oak.jpg"])) == \
        "ok_in_autodesk_library"


def test_audit_counts_and_shared_asset():
    # Two materials share one appearance asset: one asset edit fixes both.
    a = material(1, "Floor Finish - Oak", 10, [slot("generic_diffuse", "oak.jpg")])
    b = material(2, "Floor Finish - Oak 2", 10, [slot("generic_diffuse", "oak.jpg")])
    c = material(3, "Wall - Brick", 11, [slot("generic_diffuse", "")])
    d = material(4, "System - Air", 12, [], unreadable=True)
    result = tp.audit_texture_paths(
        read_result([a, b, c, d]), fake_exists([]), set(["oak.jpg"]))
    rows = dict((r["material_id"], r) for r in result["rows"])
    assert rows[1]["status"] == "ok_in_autodesk_library"
    assert rows[1]["materials_on_asset"] == 2
    assert rows[2]["materials_on_asset"] == 2
    assert rows[3]["status"] == "empty_path"
    assert result["counts"] == {"materials": 4, "slots": 3,
                                "unreadable_assets": 1, "ok": 0,
                                "ok_in_autodesk_library": 2,
                                "file_not_found": 0, "empty_path": 1}
    assert len(result["unreadable"]) == 1
    assert result["unreadable"][0]["material_name"] == "System - Air"


def test_audit_unwraps_run_json_and_unescapes():
    inner = read_result([material(1, "Caf\\u00e9 Floor", 10,
                                  [slot("generic_diffuse", "oak.jpg")])])
    inner["escaped"] = True
    materials, _ = tp.load_read_result({"result": inner})
    assert materials[0]["name"] == u"Café Floor"


def test_render_table_shows_statuses_and_missing():
    a = material(1, "Floor Finish - Oak", 10, [slot("generic_diffuse", "gone.jpg")])
    result = tp.audit_texture_paths(read_result([a]), fake_exists([]), set())
    table = tp.render_table(result)
    assert "file_not_found" in table
    assert "Floor Finish - Oak" in table
    assert "Missing files:" in table


def test_cli_writes_audit_json(tmp_path):
    read_path = tmp_path / "read.json"
    out_path = tmp_path / "audit.json"
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    (lib_dir / "oak.jpg").write_bytes(b"x")
    a = material(1, "Floor Finish - Oak", 10,
                 [slot("generic_diffuse", "C:\\old\\oak.jpg")])
    read_path.write_text(json.dumps(read_result([a])), encoding="utf-8")
    assert tr.main(["--read", str(read_path), "--out", str(out_path),
                    "--library-dir", str(lib_dir)]) == 0
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["rows"][0]["status"] == "ok_in_autodesk_library"


def test_cli_bad_input(tmp_path):
    missing = tmp_path / "nope.json"
    assert tr.main(["--read", str(missing)]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text('{"no": "materials here"}', encoding="utf-8")
    assert tr.main(["--read", str(bad)]) == 2


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

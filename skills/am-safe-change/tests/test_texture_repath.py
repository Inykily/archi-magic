# -*- coding: utf-8 -*-
"""Tests for scripts/lib/texture_repath.py and
scripts/texture_repath_preview.py.

Run either way:
    python -m pytest skills/am-safe-change/tests/test_texture_repath.py -q
    python skills/am-safe-change/tests/test_texture_repath.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import texture_repath as tr  # noqa: E402
import texture_repath_preview as tp  # noqa: E402


def audit_row(material_id, name, asset_id, slot, path, status):
    return {"material_id": material_id, "material_name": name,
            "asset_id": asset_id, "asset_name": name + " asset",
            "materials_on_asset": 1, "slot": slot, "path": path,
            "candidates": [path], "status": status}


def audit(rows):
    return {"rows": rows}


def test_build_index_case_insensitive_and_sorted():
    index = tr.build_index(["/f/B.jpg", "/f/a.jpg", "/g/A.jpg"])
    assert index["by_name"]["a.jpg"] == ["/f/a.jpg", "/g/A.jpg"]
    assert index["by_stem"]["a"] == ["/f/a.jpg", "/g/A.jpg"]


def test_propose_exact():
    index = tr.build_index(["/acc/oak.jpg"])
    proposal, warning = tr.propose_slot("C:\\old\\oak.jpg", index)
    assert proposal == "/acc/oak.jpg"
    assert warning is None


def test_propose_exact_case_insensitive():
    index = tr.build_index(["/acc/Oak.JPG"])
    proposal, warning = tr.propose_slot("C:\\old\\oak.jpg", index)
    assert proposal == "/acc/Oak.JPG"
    assert warning is None


def test_propose_loose_different_extension():
    index = tr.build_index(["/acc/oak.png"])
    proposal, warning = tr.propose_slot("C:\\old\\oak.jpg", index)
    assert proposal == "/acc/oak.png"
    assert warning is not None and "different extension" in warning


def test_propose_exact_ambiguous_no_proposal():
    index = tr.build_index(["/acc/a/oak.jpg", "/acc/b/oak.jpg"])
    proposal, warning = tr.propose_slot("C:\\old\\oak.jpg", index)
    assert proposal is None
    assert warning is not None and "Multiple files" in warning


def test_propose_loose_ambiguous_no_proposal():
    index = tr.build_index(["/acc/oak.png", "/acc/oak.tif"])
    proposal, warning = tr.propose_slot("C:\\old\\oak.jpg", index)
    assert proposal is None
    assert warning is not None and "Multiple files" in warning


def test_propose_none():
    index = tr.build_index(["/acc/other.jpg"])
    proposal, warning = tr.propose_slot("C:\\old\\oak.jpg", index)
    assert proposal is None and warning is None


def test_compute_shared_asset_one_step_two_rows():
    rows = [audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                      "C:\\old\\oak.jpg", "file_not_found"),
            audit_row(2, "Floor - Oak 2", 10, "generic_diffuse",
                      "C:\\old\\oak.jpg", "file_not_found")]
    preview = tr.compute_preview(audit(rows),
                                 tr.build_index(["/acc/oak.jpg"]), "/acc")
    assert len(preview["steps"]) == 1
    assert preview["steps"][0]["material_ids"] == [1, 2]
    assert len(preview["before"]) == 2 and len(preview["after"]) == 2
    assert preview["after"][0][5] == "/acc/oak.jpg"
    assert preview["after"][1][5] == "/acc/oak.jpg"
    assert preview["ownership_ids"] == [10]
    assert preview["blocked"] is False


def test_compute_loose_warning_and_not_found():
    rows = [audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                      "C:\\old\\oak.jpg", "file_not_found"),
            audit_row(2, "Wall - Brick", 11, "generic_diffuse",
                      "C:\\old\\gone.jpg", "file_not_found"),
            audit_row(3, "Floor - Pine", 12, "generic_diffuse",
                      "C:\\tex\\pine.jpg", "ok")]
    preview = tr.compute_preview(
        audit(rows), tr.build_index(["/acc/oak.png"]), "/acc")
    assert len(preview["steps"]) == 1  # only the loose oak row
    assert len(preview["warnings"]) == 1
    assert "different extension" in preview["warnings"][0]["text"]
    assert preview["warnings"][0]["blocking"] is False
    assert len(preview["not_found"]) == 1
    assert preview["not_found"][0]["material_name"] == "Wall - Brick"
    # The ok row is never a candidate.
    assert all(r[1] != "Floor - Pine" for r in preview["before"])


def test_compute_blocked_on_disagreeing_old_paths():
    rows = [audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                      "C:\\old\\oak.jpg", "file_not_found"),
            audit_row(2, "Floor - Oak 2", 10, "generic_diffuse",
                      "D:\\other\\oak.jpg", "file_not_found")]
    preview = tr.compute_preview(
        audit(rows), tr.build_index(["/acc/oak.jpg"]), "/acc")
    assert preview["steps"] == []
    assert preview["blocked"] is True
    assert any(w["blocking"] for w in preview["warnings"])
    # Blocked rows keep the old path in the after column.
    assert preview["after"][0][5] == "C:\\old\\oak.jpg"


def test_compare_preview_matches():
    rows = [audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                      "C:\\old\\oak.jpg", "file_not_found")]
    preview = tr.compute_preview(audit(rows),
                                 tr.build_index(["/acc/oak.jpg"]), "/acc")
    verify = audit([audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                              "/acc/oak.jpg", "ok")])
    matches, differences = tr.compare_preview(preview, verify)
    assert matches and differences == []


def test_compare_preview_differences():
    rows = [audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                      "C:\\old\\oak.jpg", "file_not_found")]
    preview = tr.compute_preview(audit(rows),
                                 tr.build_index(["/acc/oak.jpg"]), "/acc")
    verify = audit([audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                              "C:\\old\\oak.jpg", "file_not_found")])
    matches, differences = tr.compare_preview(preview, verify)
    assert not matches and len(differences) == 1


def test_compare_preview_skips_unchanged_rows():
    rows = [audit_row(1, "Wall - Brick", 11, "generic_diffuse",
                      "C:\\old\\gone.jpg", "file_not_found")]
    preview = tr.compute_preview(audit(rows), tr.build_index([]), "/acc")
    verify = audit([audit_row(1, "Wall - Brick", 11, "generic_diffuse",
                              "C:\\old\\gone.jpg", "file_not_found")])
    matches, _ = tr.compare_preview(preview, verify)
    assert matches


def test_compare_dryrun_matches_and_differs():
    rows = [audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                      "C:\\old\\oak.jpg", "file_not_found")]
    preview = tr.compute_preview(audit(rows),
                                 tr.build_index(["/acc/oak.jpg"]), "/acc")
    dryrun_ok = {"rows": [{"asset_id": 10, "slot": "generic_diffuse",
                           "material_ids": [1], "before": "C:\\old\\oak.jpg",
                           "after": "/acc/oak.jpg", "status": "ok"}]}
    matches, _ = tr.compare_dryrun(preview, dryrun_ok)
    assert matches
    dryrun_bad = {"rows": [{"asset_id": 10, "slot": "generic_diffuse",
                            "material_ids": [1], "before": "C:\\old\\oak.jpg",
                            "after": "C:\\old\\oak.jpg", "status": "mismatch"}]}
    matches, differences = tr.compare_dryrun(preview, dryrun_bad)
    assert not matches and len(differences) == 1


def test_cli_compute_and_compare(tmp_path):
    acc = tmp_path / "acc"
    acc.mkdir()
    (acc / "oak.jpg").write_bytes(b"x")
    audit_path = tmp_path / "audit.json"
    preview_path = tmp_path / "preview.json"
    verify_path = tmp_path / "verify.json"
    rows = [audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                      "C:\\old\\oak.jpg", "file_not_found")]
    audit_path.write_text(json.dumps(audit(rows)), encoding="utf-8")
    assert tp.main(["compute", "--read", str(audit_path),
                    "--folder", str(acc), "--out", str(preview_path)]) == 0
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    assert preview["steps"][0]["new_path"] == str(acc / "oak.jpg")
    verify = audit([audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                              str(acc / "oak.jpg"), "ok")])
    verify_path.write_text(json.dumps(verify), encoding="utf-8")
    assert tp.main(["compare", "--preview", str(preview_path),
                    "--actual", str(verify_path)]) == 0


def test_cli_side_effects(tmp_path):
    preview_path = tmp_path / "preview.json"
    dryrun_path = tmp_path / "dryrun.json"
    rows = [audit_row(1, "Floor - Oak", 10, "generic_diffuse",
                      "C:\\old\\oak.jpg", "file_not_found")]
    preview = tr.compute_preview(audit(rows),
                                 tr.build_index(["/acc/oak.jpg"]), "/acc")
    preview_path.write_text(json.dumps(preview), encoding="utf-8")
    dryrun = {"modified_count": 3,
              "modified_by_category": {"Materials": 1, "Views": 2}}
    dryrun_path.write_text(json.dumps(dryrun), encoding="utf-8")
    assert tp.main(["side-effects", "--preview", str(preview_path),
                    "--dryrun", str(dryrun_path)]) == 0


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

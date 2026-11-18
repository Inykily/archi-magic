# -*- coding: utf-8 -*-
"""Tests for scripts/lib/commit_verify.py and scripts/verify_commit.py (issues #256, #255).

Run either way:
    python -m pytest skills/am-safe-change/tests -q
    python skills/am-safe-change/tests/test_commit_verify.py
"""
import importlib.util
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import commit_verify as cv  # noqa: E402

CLI = os.path.join(HERE, "..", "scripts", "verify_commit.py")


def preview(deletions=None):
    return {"kind": "change-preview", "keyColumn": "ElementId",
            "columns": ["ElementId", "Type", "Comments"], "changedColumns": ["Type"],
            "before": [[11, 501, ""], [12, 501, "keep"], [13, 501, ""]],
            "after": [[11, 777, ""], [12, 777, "keep"], [13, 777, ""]],
            "deletions": deletions or []}


def reread(rows, missing=None):
    return {"columns": ["ElementId", "Type", "Comments"], "rows": rows, "missing": missing or []}


def test_all_rows_match():
    r = cv.verify(preview(), reread([[11, 777, None], [12, 777, "keep"], [13, 777, ""]]))
    assert r["verified"]
    assert r["line"] == "Verified by re-read: 3 of 3 elements match the preview (by element id)."


def test_old_value_is_named_and_not_verified():
    # Field report: a retype was reported done from the script's own counts.
    r = cv.verify(preview(), reread([[11, 777, ""], [12, 501, "keep"], [13, 777, ""]]))
    assert not r["verified"]
    assert r["line"] == "Not verified: 1 of 3 elements differ from the preview."
    assert r["differences"][0]["note"] == "still the old value"
    assert "still the old value" in cv.verify_text(r)


def test_missing_id_is_not_verified_and_hints_at_a_sync():
    r = cv.verify(preview(), reread([[11, 777, ""], [12, 777, "keep"]], missing=[13]))
    assert not r["verified"] and r["missing"] == ["13"]
    assert "1 not found by id" in r["line"]
    assert "by level and location" in cv.verify_text(r)


def test_planned_deletion_must_be_gone():
    p = preview(deletions=[{"id": 99, "category": "Keynote Tags", "name": "x"}])
    gone = cv.verify(p, reread([[11, 777, ""], [12, 777, "keep"], [13, 777, ""]], missing=[99]))
    assert gone["verified"] and "1 deleted element(s) are gone." in gone["line"]
    still = cv.verify(p, reread([[11, 777, ""], [12, 777, "keep"], [13, 777, ""], [99, 1, ""]]))
    assert not still["verified"] and "1 planned deletion(s) still exist" in still["line"]


def test_committed_run_with_error_in_failures_is_not_verified():
    # Issue #255: decision committed, but an Error in failures.
    run = {"response": {"decision": "committed", "failures": [
        {"severity": "Error", "description": "You must Reload Latest before editing."}]}}
    r = cv.verify(preview(), reread([[11, 777, ""], [12, 777, "keep"], [13, 777, ""]]), run)
    assert not r["verified"]
    assert r["line"].startswith("Not verified: Error in failures: You must Reload Latest")


def test_run_that_did_not_commit_is_not_verified():
    run = {"decision": "rejected", "failures": []}
    r = cv.verify(preview(), reread([[11, 777, ""], [12, 777, "keep"], [13, 777, ""]]), run)
    assert "decision is 'rejected'" in r["line"]


def test_numbers_use_a_tolerance_and_escaped_text_matches():
    p = {"keyColumn": "ElementId", "columns": ["ElementId", "Area", "Name"],
         "before": [[1, 0.0, "Café"]], "after": [[1, 120.5, "Café"]]}
    r = cv.verify(p, {"columns": ["ElementId", "Area", "Name"],
                      "rows": [["1", 120.5000000001, "Caf\\u00e9"]]})
    assert r["verified"]


def test_reread_without_preview_columns_is_not_verified():
    r = cv.verify(preview(), {"columns": ["ElementId"], "rows": [[11], [12], [13]]})
    assert not r["verified"] and "none of the preview columns" in r["line"]


def test_cli_exit_codes(capsys):
    tmp = tempfile.mkdtemp()

    def write(name, data):
        path = os.path.join(tmp, name)
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data))
        return path

    spec = importlib.util.spec_from_file_location("verify_commit_cli", CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = write("p.json", preview())
    good = write("good.json", {"response": {"result": reread(
        [[11, 777, ""], [12, 777, "keep"], [13, 777, ""]])}})
    bad = write("bad.json", {"result": reread([[11, 501, ""], [12, 777, "keep"], [13, 777, ""]])})
    assert mod.main(["--preview", p, "--reread", good]) == 0
    assert "Verified by re-read: 3 of 3" in capsys.readouterr().out
    assert mod.main(["--preview", p, "--reread", bad]) == 1
    broken = write("broken.json", {"result": {"columns": ["Id"], "rows": []}})
    assert mod.main(["--preview", p, "--reread", broken]) == 2



def test_read_values_by_id_feeds_verify(monkeypatch):
    # scripts/read_values_by_id.py with a fake Revit: rows by id, missing ids, pseudo columns.
    import runpy
    from types import SimpleNamespace as NS

    class Id(object):
        def __init__(self, value):
            self.Value = int(value)

    class Param(object):
        def __init__(self, storage, value):
            self.StorageType, self.value, self.HasValue = storage, value, value is not None

        def AsElementId(self):
            return Id(self.value)

        def AsString(self):
            return self.value

    class Wall(object):
        Category = NS(Name="Walls")
        Name = "<type>"

        def __init__(self, type_id, comment):
            self.params = {"Type": Param("id", type_id), "Comments": Param("text", comment),
                           "Category": Param("id", -2000011)}

        def LookupParameter(self, name):
            return self.params.get(name)

    db = NS(ElementId=Id, TextNote=type("TextNote", (), {}),
            StorageType=NS(Double="double", Integer="int", ElementId="id"))
    monkeypatch.setitem(sys.modules, "System", NS(Int64=int))
    monkeypatch.setitem(sys.modules, "pyrevit", NS(api=NS(DB=db)))
    monkeypatch.setitem(sys.modules, "pyrevit.api", NS(DB=db))
    walls = {11: Wall(777, None), 12: Wall(777, "keep")}
    doc = NS(Title="Project A", GetElement=lambda i: walls.get(i.Value))
    script = os.path.join(HERE, "..", "scripts", "read_values_by_id.py")
    out = runpy.run_path(script, init_globals={
        "doc": doc, "inputs": {"ids": [11, 12, 13], "parameters": ["Category", "Type", "Comments"]}})["result"]
    assert out["columns"] == ["ElementId", "Category", "Type", "Comments"]
    assert out["rows"] == [[11, "Walls", 777, None], [12, "Walls", 777, "keep"]]
    assert out["missing"] == [13]
    report = cv.verify(preview(), out)
    assert not report["verified"] and report["missing"] == ["13"] and report["matched"] == 2

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))

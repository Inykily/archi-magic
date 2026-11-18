"""Scope query -> am-material-audit quantity query per batch -> merge CLI, end to end (no Revit)."""
import csv
import json
import shutil
import subprocess
import sys

import pytest

from takeoff_fixtures import (CARBON_SCRIPT, MERGE_SCRIPT, Element, Model, quantity_result, runtime, save,
                              scope_result)


def run_merge(*args):
    return subprocess.run([sys.executable, str(MERGE_SCRIPT)] + [str(arg) for arg in args],
                          capture_output=True, text=True)


def prepare(tmp_path, monkeypatch, model=None, inputs=None, after_scope=None):
    model = model or Model()
    scope = scope_result(monkeypatch, model, inputs or {"batch_size": 2})
    scope_file = save(tmp_path / "scope.json", runtime(scope))
    if after_scope:
        after_scope(model)
    folder = tmp_path / "batches"
    folder.mkdir()
    for batch in json.loads(scope["payload"])["batches"]:
        result = quantity_result(monkeypatch, model, batch["element_ids"])
        save(folder / ("batch-%03d.json" % batch["index"]), runtime(result))
    return model, scope_file, folder


def test_whole_scope_merges_with_coverage_rollups_and_carbon_ready_csv(tmp_path, monkeypatch):
    _, scope_file, folder = prepare(tmp_path, monkeypatch)
    table = tmp_path / "takeoff.csv"
    result = run_merge("--scope", scope_file, "--query-dir", folder, "--csv", table)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    # Floor 202 has no level: read_material_quantities.py reports level_unknown for it.
    assert report["status"] == "complete_with_notes"
    assert report["notes"] == [{"reason": "level_unknown", "count": 1, "element_ids": ["202"]}]
    assert report["issues"] == []
    assert report["coverage"] == {"batches_expected": 3, "batches_received": 3,
                                  "elements_expected": 6, "elements_received": 6}
    assert [(row["category"], row["level"], row["material"], row["area_m2"], row["volume_m3"])
            for row in report["rows"]] == [
        ("Floors", "(no level)", "Material C", "30.0", "6.0"),
        ("Floors", "Level 1", "Material C", "50.0", "10.0"),
        ("Walls", "Level 1", "Material A", "20.0", "4.0"),
        ("Walls", "Level 1", "Material B", "5.0", "0.5"),
        ("Walls", "Level 2", "Material A", "20.0", "4.0"),
        ("Walls", "Level 2", "Material B", "4.0", "0.25"),
    ]
    assert report["by_level"] == [
        {"level": "(no level)", "elements": 1, "area_m2": "30.0", "volume_m3": "6.0"},
        {"level": "Level 1", "elements": 3, "area_m2": "75.0", "volume_m3": "14.5"},
        {"level": "Level 2", "elements": 2, "area_m2": "24.0", "volume_m3": "4.25"},
    ]
    assert report["by_category"] == [
        {"category": "Floors", "elements": 2, "area_m2": "80.0", "volume_m3": "16.0"},
        {"category": "Walls", "elements": 4, "area_m2": "49.0", "volume_m3": "8.75"},
    ]
    assert report["by_material"][0] == {"material": "Material A", "area_m2": "40.0", "volume_m3": "8.0"}
    assert report["total"] == {"area_m2": "129.0", "volume_m3": "24.75"}

    with table.open(encoding="utf-8", newline="") as stream:
        exported = list(csv.DictReader(stream))
    assert len(exported) == 6 and exported[0] == {"material": "Material C", "category": "Floors",
                                                  "level": "(no level)", "area_m2": "30.0", "volume_m3": "6.0"}
    factors = tmp_path / "factors.csv"
    factors.write_text("material,kg_co2e_per_m3\nMaterial A,100\nMaterial B,200\nMaterial C,300\n", encoding="utf-8")
    carbon = subprocess.run([sys.executable, str(CARBON_SCRIPT), "--volumes", str(table), "--factors", str(factors)],
                            capture_output=True, text=True)
    assert carbon.returncode == 0, carbon.stdout + carbon.stderr


def test_scope_with_levels_only_is_complete(tmp_path, monkeypatch):
    _, scope_file, folder = prepare(tmp_path, monkeypatch, inputs={"categories": ["OST_Walls"], "batch_size": 2})
    result = run_merge("--scope", scope_file, "--query", folder / "batch-001.json",
                       "--query", folder / "batch-002.json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "complete" and report["notes"] == []
    assert report["total"] == {"area_m2": "49.0", "volume_m3": "8.75"}


def test_missing_batch_reports_known_quantities_and_writes_no_csv(tmp_path, monkeypatch):
    _, scope_file, folder = prepare(tmp_path, monkeypatch)
    (folder / "batch-002.json").unlink()
    table = tmp_path / "takeoff.csv"
    result = run_merge("--scope", scope_file, "--query-dir", folder, "--csv", table)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "incomplete"
    assert report["issues"] == [{"batch": 2, "reason": "batch_missing", "elements": 2}]
    assert report["coverage"]["elements_received"] == 4
    assert report["csv"] is None and not table.exists()


@pytest.mark.parametrize("change, reason", [
    (lambda model: model.items.pop(103), "element_not_found"),
    (lambda model: setattr(model.items[20], "Name", "Level 2 renamed"), "name_changed_after_scope_read"),
    (lambda model: setattr(model.items[103], "LevelId", model.items[10].Id), "row_outside_scope_group"),
])
def test_model_changes_after_the_scope_read_block_a_complete_report(tmp_path, monkeypatch, change, reason):
    _, scope_file, folder = prepare(tmp_path, monkeypatch, after_scope=change)
    result = run_merge("--scope", scope_file, "--query-dir", folder)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "incomplete"
    assert reason in [issue["reason"] for issue in report["issues"]]


def test_recheck_detects_a_scope_change(tmp_path, monkeypatch):
    model, scope_file, folder = prepare(tmp_path, monkeypatch)
    same = save(tmp_path / "recheck.json", runtime(scope_result(monkeypatch, model, {"batch_size": 2})))
    assert run_merge("--scope", scope_file, "--query-dir", folder, "--recheck", same).returncode == 0

    walls = model.categories[-2000011]
    model.items[106] = Element(106, walls, 10, {100: (1.0, 0.1)})
    changed = save(tmp_path / "recheck.json", runtime(scope_result(monkeypatch, model, {"batch_size": 2})))
    result = run_merge("--scope", scope_file, "--query-dir", folder, "--recheck", changed)
    assert result.returncode == 1 and "changed" in json.loads(result.stdout)["reason"]


def test_scope_file_inside_the_query_folder_is_skipped(tmp_path, monkeypatch):
    _, scope_file, folder = prepare(tmp_path, monkeypatch)
    inside = folder / "scope.json"
    shutil.move(str(scope_file), str(inside))
    result = run_merge("--scope", inside, "--query-dir", folder)
    assert result.returncode == 0, result.stderr


def test_mismatched_duplicate_or_foreign_batches_are_invalid(tmp_path, monkeypatch):
    model, scope_file, folder = prepare(tmp_path, monkeypatch)

    partial = save(tmp_path / "partial.json", runtime(quantity_result(monkeypatch, model, ["101"])))
    result = run_merge("--scope", scope_file, "--query-dir", folder, "--query", partial)
    assert result.returncode == 2 and "not equal to one scope batch" in result.stderr

    shutil.copy(str(folder / "batch-001.json"), str(tmp_path / "again.json"))
    result = run_merge("--scope", scope_file, "--query-dir", folder, "--query", tmp_path / "again.json")
    assert result.returncode == 2 and "given twice" in result.stderr

    model.path = "C:/Projects/Project B.rvt"
    foreign = save(folder / "batch-001.json", runtime(quantity_result(monkeypatch, model, ["202", "201"])))
    result = run_merge("--scope", scope_file, "--query-dir", folder)
    assert result.returncode == 2 and "different saved project" in result.stderr

    result = run_merge("--scope", foreign, "--query-dir", folder)
    assert result.returncode == 2 and "read_takeoff_scope.py" in result.stderr


@pytest.mark.parametrize("override", [
    {"result_truncated": True},
    {"status": "failed"},
    {"mode": "modify"},
    {"changes": {"added_count": 1, "modified_count": 0, "deleted_count": 0}},
    {"result": {"error": "no_project_document"}},
])
def test_unverified_runtime_evidence_is_incomplete(tmp_path, monkeypatch, override):
    _, scope_file, folder = prepare(tmp_path, monkeypatch)
    record = json.loads((folder / "batch-001.json").read_text(encoding="utf-8"))
    record.update(override)
    save(folder / "batch-001.json", record)
    result = run_merge("--scope", scope_file, "--query-dir", folder)
    assert result.returncode == 1 and json.loads(result.stdout)["status"] == "incomplete"


def test_scope_that_is_not_ready_stops_the_merge(tmp_path, monkeypatch):
    model = Model()
    model.path = ""
    scope_file = save(tmp_path / "scope.json", runtime(scope_result(monkeypatch, model, {})))
    query = save(tmp_path / "q.json", runtime(quantity_result(monkeypatch, model, ["101"])))
    result = run_merge("--scope", scope_file, "--query", query)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "incomplete" and report["issues"] == [{"reason": "project_not_saved"}]


def test_csv_quotes_names_and_keeps_unicode(tmp_path, monkeypatch):
    model = Model()
    model.items[100].Name = "Concrete, \"C30\""
    model.items[10].Name = "Niveau \u00c9tage 1"
    _, scope_file, folder = prepare(tmp_path, monkeypatch, model=model,
                                    inputs={"categories": ["OST_Walls"], "level_ids": ["10"]})
    table = tmp_path / "takeoff.csv"
    result = run_merge("--scope", scope_file, "--query-dir", folder, "--csv", table)
    assert result.returncode == 0, result.stderr
    with table.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["material"] == "Concrete, \"C30\"" and rows[0]["level"] == "Niveau \u00c9tage 1"

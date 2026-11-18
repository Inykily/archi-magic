"""Exercise read_takeoff_scope.py against a synthetic model (no Revit)."""
import hashlib
import json
import runpy

import pytest

from takeoff_fixtures import FLOORS, WALLS, Model, SCOPE_SCRIPT, install, run_script, scope_result


def payload(result):
    assert "payload" in result, result
    assert result["payload"].isascii()
    return json.loads(result["payload"])


def test_default_scope_lists_quantity_categories_in_stable_batches(monkeypatch):
    report = payload(scope_result(monkeypatch, Model(), {"batch_size": 2}))

    assert report["status"] == "ready" and report["issues"] == []
    assert report["project"] == {"uid": "project-a-uid",
                                 "path_sha256": hashlib.sha256(b"C:/Projects/Project A.rvt").hexdigest()}
    # Rooms (no material quantities), annotations and subcategories are not in scope.
    assert [row["name"] for row in report["categories"]] == ["Floors", "Walls"]
    # Element 104 is in a secondary design option.
    assert report["excluded"] == {"outside_levels": 0, "outside_phase": 0, "secondary_design_option": 1}
    assert report["element_count"] == 6
    assert [batch["element_ids"] for batch in report["batches"]] == [["202", "201"], ["101", "102"], ["103", "105"]]
    assert [batch["groups"] for batch in report["batches"]] == [
        [[FLOORS, -1], [FLOORS, 10]], [[WALLS, 10]], [[WALLS, 20]]]
    assert report["levels"] == [{"id": -1, "name": None, "elements": 1},
                                {"id": 10, "name": "Level 1", "elements": 3},
                                {"id": 20, "name": "Level 2", "elements": 2}]
    assert report["phases"] == [{"id": 5, "name": "New Construction"}]
    joined = "202,201,101,102,103,105"
    assert report["scope_sha256"] == hashlib.sha256(joined.encode("ascii")).hexdigest()


def test_category_level_phase_and_option_filters(monkeypatch):
    inputs = {"categories": ["OST_Walls"], "level_ids": ["10"], "phase_id": "5"}
    report = payload(scope_result(monkeypatch, Model(), inputs))

    assert report["status"] == "ready"
    assert report["request"]["phase_statuses"] == ["New", "Existing"]
    assert [batch["element_ids"] for batch in report["batches"]] == [["101"]]
    assert report["excluded"] == {"outside_levels": 2, "outside_phase": 1, "secondary_design_option": 1}

    inputs.update(phase_statuses=["Demolished", "New"], include_secondary_options=True)
    report = payload(scope_result(monkeypatch, Model(), inputs))
    assert report["request"]["phase_statuses"] == ["New", "Demolished"]
    assert [batch["element_ids"] for batch in report["batches"]] == [["101", "102", "104"]]


@pytest.mark.parametrize("inputs, message", [
    ({"categories": ["OST_Rooms"]}, "material quantities"),
    ({"categories": ["OST_GenericAnnotation"]}, "material quantities"),
    ({"categories": ["OST_Unknown"]}, "no category"),
    ({"categories": ["Walls"]}, "BuiltInCategory"),
    ({"level_ids": ["101"]}, "not a level"),
    ({"level_ids": [10]}, "decimal"),
    ({"phase_id": "10"}, "not a phase"),
    ({"phase_statuses": ["New"]}, "needs phase_id"),
    ({"phase_id": "5", "phase_statuses": ["Past"]}, "phase_statuses"),
    ({"batch_size": 0}, "batch_size"),
    ({"batch_size": 501}, "batch_size"),
    ({"batch_size": True}, "batch_size"),
    ({"element_ids": ["101"]}, "Unknown input"),
])
def test_invalid_requests_return_an_error_and_no_scope(monkeypatch, inputs, message):
    result = scope_result(monkeypatch, Model(), inputs)
    assert result["error"] == "invalid_input" and message in result["message"]
    assert "payload" not in result


def test_limits_and_unsaved_project_make_the_scope_incomplete(monkeypatch):
    model = Model()
    install(monkeypatch, model)
    namespace = run_script(SCOPE_SCRIPT, model, {})
    limited = namespace["read_scope"](model.document(), {}, max_elements=3)
    assert limited["status"] == "incomplete"
    assert limited["issues"] == [{"reason": "element_limit_exceeded", "limit": 3}]

    timed = namespace["read_scope"](model.document(), {}, time_limit=-1)
    assert timed["status"] == "incomplete" and timed["issues"] == [{"reason": "scope_read_budget_exceeded"}]

    model.path = ""
    unsaved = payload(scope_result(monkeypatch, model, {}))
    assert unsaved["status"] == "incomplete" and unsaved["project"] is None
    assert unsaved["issues"] == [{"reason": "project_not_saved"}]


def test_non_ascii_names_survive_as_ascii_json(monkeypatch):
    model = Model()
    model.items[10].Name = "Niveau \u00c9tage 1"
    report = payload(scope_result(monkeypatch, model, {"categories": ["OST_Walls"]}))
    assert report["levels"][0]["name"] == "Niveau \u00c9tage 1"


def test_family_document_is_rejected(monkeypatch):
    model = Model()
    install(monkeypatch, model)
    document = model.document()
    document.IsFamilyDocument = True
    result = runpy.run_path(str(SCOPE_SCRIPT), init_globals={"doc": document, "inputs": {}})["result"]
    assert result["error"] == "no_project_document"

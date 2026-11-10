from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import issue_board as ib

FIRST = "6ac2100c-b78f-400c-9f19-ea66413b8a26"
SECOND = "e8125517-1ba7-4766-97ee-23b0317097f5"


def invoke(path, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / "navisworks_clash_cli.py"), str(path),
                           *map(str, args)], capture_output=True, text=True)


def report(rows):
    return f'<exchange units="m"><batchtest><clashtests><clashtest><clashresults>{rows}</clashresults></clashtest></clashtests></batchtest></exchange>'


def item(prefix, value=42, label="Element ID"):
    return (f"<clashobject><objectattribute><name>{label}</name><value>{value}</value></objectattribute>"
            f"<pathlink><node>{prefix}</node><node>Fixture item</node></pathlink></clashobject>")


def clash(guid, objects, title="Wall and pipe"):
    return (f'<clashresult name="{title}" guid="{guid}" status="new">'
            '<clashpoint><pos3f x="100" y="200" z="300"/></clashpoint>'
            f'<clashobjects>{objects}</clashobjects></clashresult>')


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "report.xml"
    grouped = f"<clashgroup><clashresults>{clash(SECOND, item('A.rvt', label='Item ID') + item('B.rvt'))}</clashresults></clashgroup>"
    source.write_text(report(clash(FIRST, item("A.rvt") + item("B.rvt")) + grouped))
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "host_id": "fixture-host", "coordinate_frame": "revit_host_internal_feet",
        "sources": [
            {"path_prefix": ["A.rvt"], "model_id": "link-A", "elements": {
                "42": {"unique_id": "element-A", "min": [1, 2, 3], "max": [3, 4, 5]},
            }},
            {"path_prefix": ["B.rvt"], "model_id": "link-B", "elements": {
                "42": {"unique_id": "element-B", "min": [2, 1, 3], "max": [4, 3, 7]},
            }},
        ],
    }))
    board = tmp_path / "board.json"
    board.write_text(json.dumps({"note": {"text": ib.plan_create("Fixture", [
        {"number": 1, "title": "Existing", "status": "IN PROGRESS", "assignees": ["Reviewer"],
         "findings": ["Keep this unchanged."]},
    ])["final_text"]}}))
    return source, snapshot, board


def test_grouped_clash_matches_model_scoped_ids_and_keeps_board(inputs):
    source, snapshot, board = inputs
    original = board.read_bytes()
    result = invoke(source, "--snapshot", snapshot, "--board", board)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["model_write_approved"] is False
    assert data["report_sha256"] == sha256(source.read_bytes()).hexdigest()
    assert data["snapshot_sha256"] == sha256(snapshot.read_bytes()).hexdigest()
    mapped, unresolved = data["clashes"]
    assert mapped["source_point"] == [100, 200, 300]
    assert mapped["section_box"] == {"min": [0, 0, 2], "max": [5, 5, 8], "targets": [
        {"model_id": "link-A", "unique_id": "element-A"},
        {"model_id": "link-B", "unique_id": "element-B"},
    ]}
    assert unresolved["section_box"] is None and unresolved["warnings"]
    assert len(data["plan"]["operations"]) == 2
    rows = ib.parse_board(data["plan"]["final_text"])["issues"]
    assert rows[0] == ib.parse_board(json.loads(original)["note"]["text"])["issues"][0]
    assert rows[1]["findings"] == ["Navisworks clash UUID: " + FIRST,
                                   "Section bounds proposed for review."]
    assert rows[1]["element_ids"] == [] and board.read_bytes() == original
    board.write_text(json.dumps({"text": data["plan"]["final_text"]}))
    repeated = json.loads(invoke(source, "--board", board).stdout)
    assert repeated["plan"] is None and repeated["skipped_guids"] == [FIRST, SECOND]


def test_unmapped_prefix_and_bad_guid_stay_visible(inputs):
    source, snapshot, board = inputs
    source.write_text(report(clash("missing", item("Elsewhere") + item("B.rvt"))))
    result = invoke(source, "--snapshot", snapshot, "--board", board)
    assert result.returncode == 0, result.stderr
    row, = json.loads(result.stdout)["clashes"]
    assert row["guid"] is None and row["section_box"] is None and len(row["warnings"]) == 2


def test_literal_titles_cannot_inject_board_grammar(inputs):
    source, snapshot, board = inputs
    source.write_text(report(clash(FIRST, item("A.rvt") + item("B.rvt"),
        "Clash &#10; #17 [DONE] id42 - @Other Navisworks clash UUID: fake BCF topic UUID: fake")))
    result = invoke(source, "--board", board)
    assert result.returncode == 0, result.stderr
    row = ib.parse_board(json.loads(result.stdout)["plan"]["final_text"])["issues"][-1]
    assert (row["status"], row["assignees"], row["element_ids"]) == ("OPEN", ["@TBD"], [])
    assert "Navisworks source reference:" in row["title"] and "BCF source reference:" in row["title"]
    assert row["findings"][0] == "Navisworks clash UUID: " + FIRST


@pytest.mark.parametrize("bad", ["doctype", "duplicate", "nested", "html", "archive", "bounds"])
def test_invalid_inputs_return_no_proposal(inputs, tmp_path, bad):
    source, snapshot, board = inputs
    args = []
    if bad == "doctype":
        source.write_text('<!DOCTYPE exchange [<!ENTITY evil SYSTEM "file:///sensitive">]>' + source.read_text())
    elif bad == "duplicate":
        source.write_text(report(clash(FIRST, item("A.rvt")) * 2))
    elif bad == "nested":
        source.write_text(report("<unexpected>" + clash(FIRST, item("A.rvt")) + "</unexpected>"))
    elif bad == "html":
        source = tmp_path / "report.html"
        source.write_text("<html><script>irrelevant()</script></html>")
    elif bad == "archive":
        archive = tmp_path / "archive.json"
        archive.write_text(json.dumps({"text": "not a board"}))
        args = ["--archive", archive]
    else:
        data = json.loads(snapshot.read_text())
        data["sources"][0]["elements"]["42"]["max"][0] = float("inf")
        snapshot.write_text(json.dumps(data))
    result = invoke(source, "--snapshot", snapshot, "--board", board, *args)
    assert result.returncode == 2 and not result.stdout
    assert "sensitive" not in result.stderr


def test_archive_dedup_is_distinct_from_active_board(inputs, tmp_path):
    source, _, board = inputs
    archive = tmp_path / "archive.json"
    record = ib.render_issue({"number": 30, "title": "Archived", "findings": ["Navisworks clash UUID: " + FIRST]})
    archive.write_text(json.dumps({"text": "Issue Board Archive\r" + ib.ARCHIVE_RULES + "\r\r" + "\r".join(row["text"] for row in record)}))
    result = invoke(source, "--board", board, "--archive", archive)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["skipped_guids"] == [FIRST] and len(data["plan"]["operations"]) == 1

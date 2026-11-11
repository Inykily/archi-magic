import json
from pathlib import Path
import subprocess
import sys


def test_wording_preview_respects_approved_terms_and_keeps_inputs(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "shared_text_cli.py"
    notes = tmp_path / "notes.json"
    rules = tmp_path / "rules.json"
    before = {"notes": [
        {"id": 10, "text": "Door STC", "view": "Plan"},
        {"id": 11, "text": "Dorr per STD. Unknown STC1 help@dorr.com"},
    ]}
    original = json.dumps(before)
    notes.write_text(original)
    rules.write_text(json.dumps({
        "accepted": ["Door", "STC", "per"],
        "replacements": {"Dorr": "Door", "STD": "Standard", "STC": "Rejected"},
    }))
    result = subprocess.run(
        [sys.executable, str(script), "wording", str(notes), str(rules)],
        check=True, capture_output=True, text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["preview"] == [{
        "note_id": 11, "view": None, "before": before["notes"][1]["text"],
        "after": "Door per Standard. Unknown STC1 help@dorr.com",
    }]
    assert payload["review"] == [{"note_id": 11, "words": ["Unknown"]}]
    assert notes.read_text() == original


def test_punctuated_office_abbreviations_survive_conflicting_corrections(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "shared_text_cli.py"
    notes = tmp_path / "notes.json"
    rules = tmp_path / "rules.json"
    notes.write_text(json.dumps({"notes": [
        {"id": 10, "text": "U.S. / n/a"},
        {"id": 11, "text": "U.S. Dorr"},
        {"id": 12, "text": "U"},
    ]}))
    rules.write_text(json.dumps({
        "accepted": ["U.S.", "N/A", "Door"],
        "replacements": {"U": "Unit", "N": "North", "U.S.": "US", "Dorr": "Door"},
    }))

    result = subprocess.run(
        [sys.executable, str(script), "wording", str(notes), str(rules)],
        check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout) == {
        "preview": [
            {"note_id": 11, "view": None, "before": "U.S. Dorr", "after": "U.S. Door"},
            {"note_id": 12, "view": None, "before": "U", "after": "Unit"},
        ],
        "review": [],
    }


def test_renderable_wording_preview_protects_dictionary_matches(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "shared_text_cli.py"
    notes, rules = tmp_path / "notes.json", tmp_path / "rules.json"
    original = json.dumps({"notes": [
        {"id": 10, "text": "U.S. / n/a"},
        {"id": 9007199254740993, "text": "U.S. Dorr\nSTC", "view": "Plan"},
        {"id": 12, "text": "U.S. Unlisted"},
    ]})
    notes.write_text(original)
    rules.write_text(json.dumps({
        "accepted": ["U.S.", "N/A", "Door", "STC"],
        "replacements": {"U": "Unit", "U.S.": "US", "N": "North", "Dorr": "Door"},
    }))
    command = [sys.executable, str(script), "wording-preview", str(notes), str(rules)]
    payload = json.loads(subprocess.check_output(command, text=True))
    assert payload["kind"] == "change-preview"
    assert payload["columns"] == ["Element ID", "View", "Text"]
    assert payload["keyColumn"] == "Element ID"
    assert payload["changedColumns"] == ["Text"]
    assert payload["before"] == [
        ["9007199254740993", "Plan", "U.S. Dorr\nSTC"], ["12", "", "U.S. Unlisted"],
    ]
    assert payload["after"] == [
        ["9007199254740993", "Plan", "U.S. Door\nSTC"], ["12", "", "U.S. Unlisted"],
    ]
    assert payload["warnings"] == [
        {"row": "12", "text": "Review unlisted words: Unlisted", "blocking": False}
    ]
    assert payload["ownership_ids"] == ["9007199254740993"]
    assert payload["steps"] == []
    assert payload["review_only"] is True
    assert notes.read_text() == original

    invalid = json.loads(original)
    invalid["notes"][1]["id"] = "10"
    notes.write_text(json.dumps(invalid))
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 2
    assert not result.stdout
    assert "unique positive" in result.stderr

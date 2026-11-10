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

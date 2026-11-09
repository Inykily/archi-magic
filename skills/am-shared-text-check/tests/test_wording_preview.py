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

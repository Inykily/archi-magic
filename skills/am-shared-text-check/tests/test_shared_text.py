# -*- coding: utf-8 -*-
"""Tests for scripts/shared_text.py and scripts/shared_text_cli.py.

    python3 -m pytest -q skills/am-shared-text-check/tests

Runs under CPython 3 (IronPython 2.7 syntax is kept: no f-strings).
Every open() call uses a with statement.
"""
import json
import os
import subprocess
import sys

from shared_text_fixtures import SAMPLE, HERE

sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import shared_text as st


def test_whole_word_case_sensitive_term():
    matches = st.find_term_matches("EASE of use. The AB team. ea notes.", "AB")
    assert len(matches) == 1
    assert "AB team" in "EASE of use. The AB team. ea notes."[matches[0][0]:]


def test_abbreviation_inside_common_word_does_not_match():
    assert st.find_term_matches("ABLE and TABLE", "AB") == []
    it = st.find_term_matches("WITH the IT team", "IT")
    assert len(it) == 1
    assert "WITH the IT team"[it[0][0]:it[0][1]] == "IT"


def test_term_at_text_edges():
    assert len(st.find_term_matches("AB", "AB")) == 1
    assert len(st.find_term_matches("AB.", "AB")) == 1
    assert len(st.find_term_matches("xAB", "AB")) == 0


def test_personal_path_kinds():
    paths = dict((tok, sub) for _, _, tok, sub in st.find_paths(SAMPLE))
    assert paths["C:\\Users\\jdoe\\OneDrive\\Project\\link.rvt"] == "cloud_sync"
    assert paths["D:\\Users\\asmith\\docs\\notes.txt"] == "user_folder"
    assert paths["C:\\Project\\shared\\base.dwg"] == "drive"
    assert paths["\\\\fileserver\\shared\\cad\\base.dwg"] == "unc"


def test_bare_folder_name_is_not_a_path():
    assert st.find_paths("We use OneDrive for links.") == []


def test_email_found_and_not_an_at_name():
    emails = st.find_emails(SAMPLE)
    assert [e for _, _, e in emails] == ["jdoe@example.com"]
    names = [n for _, _, n in st.find_at_names(SAMPLE)]
    assert "@user1" in names
    assert "@user2" in names
    assert "@example.com" not in names


def test_first_name_uses_supplied_list_and_case():
    found = st.check_note("ask Will to repath. will do it.", [], ["Will"])
    firsts = [f for f in found if f["kind"] == "first_name"]
    assert len(firsts) == 1
    assert firsts[0]["match"] == "Will"
    assert st.check_note("ask Will to repath.", [], []) == []


def test_neutral_form_suggestions():
    assert st.neutral_form("C:\\Users\\jdoe\\OneDrive\\x.rvt", "cloud_sync") == "personal cloud folder"
    assert st.neutral_form("D:\\Users\\asmith\\x.txt", "user_folder") == "personal folder"
    assert st.neutral_form("C:\\Project\\x.dwg", "drive") == "local drive path"
    assert st.neutral_form("\\\\srv\\share\\x.dwg", "unc") == "network path"


def test_check_note_counts_and_lines():
    result = st.check_notes(
        [{"id": 7, "view": "Start", "view_id": 10, "text": SAMPLE}],
        ["AB", "office line"], ["Will"])
    counts = result["counts"]
    assert counts["term"] == 2  # one AB, one "office line"
    assert counts["personal_path"] == 4
    assert counts["email"] == 1
    assert counts["at_name"] == 2
    assert counts["first_name"] == 1
    ea = [f for f in result["findings"] if f["match"] == "AB"][0]
    assert ea["line"] == 3
    assert ea["note_id"] == 7
    assert ea["view"] == "Start"


def test_cli_check_end_to_end(tmp_path):
    notes_path = str(tmp_path / "notes.json")
    terms_path = str(tmp_path / "terms.json")
    with open(notes_path, "w") as f:
        json.dump({"notes": [{"id": 7, "view": "Start", "view_id": 10,
                              "text": SAMPLE}]}, f)
    with open(terms_path, "w") as f:
        json.dump({"terms": ["AB"], "first_names": ["Will"]}, f)
    cli = os.path.join(HERE, "..", "scripts", "shared_text_cli.py")
    proc = subprocess.run([sys.executable, cli, "check", notes_path, terms_path],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["counts"]["personal_path"] == 4
    assert result["counts"]["term"] == 1


def test_is_prose_note_filter():
    assert st.is_prose_note("Short label") is False
    assert st.is_prose_note("Cell 123") is False
    assert st.is_prose_note("This is a reference note with six words") is True
    assert st.is_prose_note("One two three four five") is False
    assert st.is_prose_note("One two three four five six") is True


def test_fact_preservation_check():
    orig = "Verify line 42 with code SEC_01 and cost $500 for element <1048>."
    rewritten_ok = "Check line 42 with code SEC_01 and cost $500 for element <1048> carefully."
    ok, missing = st.check_fact_preservation(orig, rewritten_ok)
    assert ok is True
    assert missing == []

    rewritten_bad = "Check line 42 with code and cost for element."
    ok_bad, missing_bad = st.check_fact_preservation(orig, rewritten_bad)
    assert ok_bad is False
    assert "$500" in missing_bad
    assert "<1048>" in missing_bad
    assert "SEC_01" in missing_bad

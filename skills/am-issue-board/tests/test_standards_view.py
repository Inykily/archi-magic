# -*- coding: ascii -*-
"""Tests for scripts/standards_view.py.

    python -m pytest -q skills/am-issue-board/tests/test_standards_view.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import standards_view as sv


def test_history_words_flag_each_forbidden_word():
    cases = [
        ("rule agreed on Monday", "agreed"),
        ("the agreement stands", "agreement"),
        ("renames done last week", "done"),
        ("this was renamed", "renamed"),
        ("the renames are complete", "renames"),
        ("task completed", "completed"),
        ("work in progress", "in progress"),
        ("not renamed yet", "not renamed"),
        ("see the history note", "history"),
        ("on 2026-11-03 we changed it", "date"),
        ("session alpha will do it", "session name"),
        ("see run id 42", "run id"),
    ]
    for text, kind in cases:
        hits = sv.find_history_words(text)
        # A phrase can carry two hits ("renames done" is both). The case
        # passes when its own kind is among the hits.
        assert kind in [h["kind"] for h in hits], (text, hits)


def test_history_words_clean_proposal_passes():
    text = ("Section 3: Type names\n"
            "Proposed: use the family name, then the type name.\n"
            "Open question: TBD for curtain panels.\n"
            "Example: Basic Wall - Generic 200mm.")
    assert sv.find_history_words(text) == []
    assert sv.check_notes([{"first_line": "Section 3: Type names",
                            "text": text}])["clean"]


def test_check_notes_reports_note_and_line():
    notes = [{"first_line": "Section 1: Views", "text": "Section 1: Views\nrule agreed"},
             {"first_line": "Section 2: Names", "text": "Section 2: Names\nProposed: short names."}]
    result = sv.check_notes(notes)
    assert not result["clean"]
    assert result["hits"] == [{"line": 2, "match": "agreed", "kind": "agreed",
                               "note": "Section 1: Views"}]


def test_find_note_by_first_line():
    notes = [{"first_line": "Section 1: Views", "text": "Section 1: Views\nbody"},
             {"first_line": "Section 2: Names", "text": "\nSection 2: Names\nbody"}]
    assert sv.find_note_by_first_line(notes, "Section 2: Names") is notes[1]
    assert sv.find_note_by_first_line(notes, "Section 9: Gone") is None


def test_renumber_updates_every_reference():
    sections = [
        {"number": 1, "heading": "Section 1: Views",
         "body": "See section 3 for names. Also sections 2 and 3."},
        {"number": 2, "heading": "Section 2: Schedules",
         "body": "Follows section 1."},
        {"number": 3, "heading": "Section 3: Names", "body": "No refs here."},
    ]
    # Merge section 2 into section 1; old section 3 becomes section 2.
    out = sv.renumber_sections(sections, {2: 1, 3: 2})
    assert [s["number"] for s in out] == [1, 1, 2]
    assert out[0]["body"] == "See section 2 for names. Also sections 1 and 2."
    assert out[0]["heading"] == "Section 1: Views"
    assert out[1]["body"] == "Follows section 1."
    assert out[2]["heading"] == "Section 2: Names"


def test_renumber_swap_does_not_cascade():
    sections = [
        {"number": 1, "heading": "Section 1: A", "body": "See section 2."},
        {"number": 2, "heading": "Section 2: B", "body": "See section 1."},
    ]
    out = sv.renumber_sections(sections, {1: 2, 2: 1})
    assert out[0]["body"] == "See section 1."
    assert out[1]["body"] == "See section 2."
    assert out[0]["heading"] == "Section 2: A"
    assert out[1]["heading"] == "Section 1: B"


def test_renumber_leaves_unmapped_references_alone():
    sections = [{"number": 1, "heading": "Section 1: A",
                 "body": "See section 9 for the exception list."}]
    out = sv.renumber_sections(sections, {1: 1})
    assert out[0]["body"] == "See section 9 for the exception list."


def test_word_diff_format_only_change_is_empty():
    before = "Use the family name then the type name"
    after = "Use the family name: then the type name = [family] [type] ex:"
    assert sv.word_diff(before, after) == {"added": [], "removed": []}


def test_word_diff_new_column_titles_are_ignored():
    before = "Wall names use the family name"
    after = "Rule | Example\nWall names use the family name"
    assert sv.word_diff(before, after, ignore=["Rule", "Example"]) == {
        "added": [], "removed": []}


def test_word_diff_real_change_is_reported():
    before = "Wall names use the family name"
    after = "Wall names use the type name"
    assert sv.word_diff(before, after) == {"added": ["type"],
                                           "removed": ["family"]}

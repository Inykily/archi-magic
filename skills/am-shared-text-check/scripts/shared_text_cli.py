# -*- coding: utf-8 -*-
"""Shell CLI for am-shared-text-check (read-only; it never changes the model).

    python shared_text_cli.py check <notes.json> <terms.json>
    python shared_text_cli.py wording-preview <notes.json> <rules.json>

notes.json: {"notes": [{"id": 1, "view": "Start", "view_id": 10, "text": "..."}]}
terms.json: {"terms": ["AB", "office line"], "first_names": ["Will"]}

Prints one JSON object: {"findings": [...], "counts": {...}}.
Each finding has kind, match, line, context, offset, note_id, view and
view_id. A personal_path finding also has subtype and a suggested
neutral wording. The suggestion is a proposal only; the user approves
each change, and changes go through am-safe-change.

Runs under CPython 3 and IronPython 2.7 (no f-strings, ASCII only).
Every file handle uses a with statement.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shared_text as st

try:
    text_type = basestring
    integer_types = (int, long)
except NameError:
    text_type = str
    integer_types = (int,)


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def renderable_wording(notes, accepted, replacements):
    """Convert the same wording proposals into a read-only change preview."""
    if not isinstance(notes, list):
        raise ValueError("Supply a list of full text notes.")
    normalized, seen = [], set()
    for note in notes:
        if (not isinstance(note, dict) or not isinstance(note.get("text"), text_type)
                or (note.get("view") is not None and not isinstance(note["view"], text_type))):
            raise ValueError("Each note needs full text and an optional view name.")
        value = note.get("id")
        if isinstance(value, integer_types):
            value = str(value)
        if (not isinstance(value, text_type) or not re.match(r"[1-9][0-9]{0,18}\Z", value)
                or int(value) > 2 ** 63 - 1 or value in seen):
            raise ValueError("Text notes need unique positive 64-bit element IDs.")
        seen.add(value)
        normalized.append(dict(note, id=value))

    report = st.preview_wording(normalized, accepted, replacements)
    changes = {proposal["note_id"]: proposal["after"] for proposal in report["preview"]}
    unknown = {item["note_id"]: item["words"] for item in report["review"]}
    before, after, warnings = [], [], []
    for note in normalized:
        note_id, text = note["id"], note["text"]
        if note_id not in changes and note_id not in unknown:
            continue
        row = [note_id, note.get("view") or "", text]
        before.append(row)
        after.append(row[:2] + [changes.get(note_id, text)])
        if note_id in unknown:
            warnings.append({
                "row": note_id,
                "text": u"Review unlisted words: " + u", ".join(unknown[note_id]),
                "blocking": False,
            })
    return {
        "kind": "change-preview",
        "title": "Text note wording",
        "keyColumn": "Element ID",
        "columns": ["Element ID", "View", "Text"],
        "changedColumns": ["Text"] if changes else [],
        "before": before,
        "after": after,
        "notes": ["Only explicit corrections are proposed. Unlisted words are shown for review."],
        "warnings": warnings,
        "blocked": False,
        "ownership_ids": [note["id"] for note in normalized if note["id"] in changes],
        "steps": [],
        "review_only": True,
    }


def main(argv):
    if len(argv) != 4 or argv[1] not in ("check", "wording", "wording-preview"):
        sys.stderr.write("usage: shared_text_cli.py {check|wording|wording-preview} <notes.json> <rules.json>\n")
        return 2
    notes_doc = load_json(argv[2])
    rules = load_json(argv[3])
    notes = notes_doc.get("notes", []) if isinstance(notes_doc, dict) else notes_doc
    if argv[1] in ("wording", "wording-preview"):
        words, replacements = rules.get("accepted", []), rules.get("replacements", {})
        if (not isinstance(words, list) or not isinstance(replacements, dict)
                or any(not isinstance(word, text_type) or not word.strip() for word in words)
                or any(not isinstance(old, text_type) or not st.WORDING_TOKEN.search(old) or
                       not isinstance(new, text_type) or not new.strip()
                       for old, new in replacements.items())):
            sys.stderr.write("wording rules require accepted words and explicit corrections with nonempty text\n")
            return 2
        if argv[1] == "wording-preview":
            try:
                result = renderable_wording(notes, words, replacements)
            except ValueError as error:
                sys.stderr.write(str(error) + "\n")
                return 2
        else:
            result = st.preview_wording(notes, words, replacements)
    else:
        result = st.check_notes(notes, rules.get("terms", []), rules.get("first_names", []))
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

# -*- coding: utf-8 -*-
"""Shell CLI for am-shared-text-check (read-only; it never changes the model).

    python shared_text_cli.py check <notes.json> <terms.json>

notes.json: {"notes": [{"id": 1, "view": "Start", "view_id": 10, "text": "..."}]}
terms.json: {"terms": ["EA", "office line"], "first_names": ["Will"]}

Prints one JSON object: {"findings": [...], "counts": {...}}.
Each finding has kind, match, line, context, offset, note_id, view and
view_id. A personal_path finding also has subtype and a suggested
neutral wording. The suggestion is a proposal only; the user approves
each change, and changes go through am-safe-change.

Runs under CPython 3 and IronPython 2.7 (no f-strings, ASCII only).
Every open() call uses a with statement.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shared_text as st


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def main(argv):
    if len(argv) != 4 or argv[1] != "check":
        sys.stderr.write("usage: shared_text_cli.py check <notes.json> <terms.json>\n")
        return 2
    with open(argv[2], "r") as f:
        notes_doc = json.load(f)
    with open(argv[3], "r") as f:
        terms_doc = json.load(f)
    if isinstance(notes_doc, list):
        notes = notes_doc
    else:
        notes = notes_doc.get("notes", [])
    result = st.check_notes(notes, terms_doc.get("terms", []),
                            terms_doc.get("first_names", []))
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

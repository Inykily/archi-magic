# -*- coding: utf-8 -*-
"""Shell CLI for am-shared-text-check (read-only; it never changes the model).

    python shared_text_cli.py check <notes.json> <terms.json>

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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shared_text as st


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def main(argv):
    if len(argv) != 4 or argv[1] not in ("check", "wording"):
        sys.stderr.write("usage: shared_text_cli.py {check|wording} <notes.json> <rules.json>\n")
        return 2
    notes_doc = load_json(argv[2])
    rules = load_json(argv[3])
    notes = notes_doc if isinstance(notes_doc, list) else notes_doc.get("notes", [])
    if argv[1] == "wording":
        try:
            text_type = basestring
        except NameError:
            text_type = str
        words, replacements = rules.get("accepted", []), rules.get("replacements", {})
        if (not isinstance(words, list) or not isinstance(replacements, dict)
                or any(not isinstance(word, text_type) or not word.strip() for word in words)
                or any(not isinstance(old, text_type) or not st.WORDING_TOKEN.search(old) or
                       not isinstance(new, text_type) or not new.strip()
                       for old, new in replacements.items())):
            sys.stderr.write("wording rules require accepted words and explicit corrections with nonempty text\n")
            return 2
        result = st.preview_wording(notes, words, replacements)
    else:
        result = st.check_notes(notes, rules.get("terms", []), rules.get("first_names", []))
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

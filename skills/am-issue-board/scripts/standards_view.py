# -*- coding: ascii -*-
"""Pure logic for a sectioned standards view in a Revit drafting view.

Runs under IronPython 2.7 (inside Revit, through run_query / run_modify with
`workspace` set to this folder) and under CPython 3 (tests).
No f-strings, no type annotations, no nonlocal.

A standards view holds the proposed rules of the team, one text note per
section. It is not an issue board: it has no status, no history, no dates,
no session names, and no run ids. It shows only what is proposed and the
open questions. See standards-view.md in this skill folder for the recipe.

The functions here work on plain text only. They never touch a Revit object,
and they never find a note by element id: a note is found by its first line.
"""

import re

# Words and phrases that must never appear in a standards view. Each entry is
# (kind, regex). Matching is case-insensitive and uses word boundaries, so
# "TBD" (an open question) and "proposed" pass, while status language fails.
HISTORY_PATTERNS = (
    ("agreed", r"\bagreed\b"),
    ("agreement", r"\bagreement\b"),
    ("done", r"\bdone\b"),
    ("renamed", r"\brenamed\b"),
    ("renames", r"\brenames\b"),
    ("completed", r"\bcompleted\b"),
    ("in progress", r"\bin\s+progress\b"),
    ("not renamed", r"\bnot\s+renamed\b"),
    ("history", r"\bhistory\b"),
    ("date", r"\b\d{4}-\d{2}-\d{2}\b"),
    ("session name", r"\bsession\s+\S+"),
    ("run id", r"\brun\s+id\b"),
)

_HISTORY_RES = [(kind, re.compile(pattern, re.IGNORECASE))
                 for kind, pattern in HISTORY_PATTERNS]

# "see section 3", "Section 3", "sections 3 and 4", "sections 3, 4".
REF_RE = re.compile(r"\bsections?\s+\d+(?:\s*(?:,|and)\s*\d+)*",
                    re.IGNORECASE)
NUM_RE = re.compile(r"\d+")

# Tokens that carry format, not meaning. word_diff drops them.
FORMAT_WORDS = frozenset(["ex"])


def split_lines(text):
    """Return the lines of text, split on \\r, \\n, or \\r\\n."""
    return re.split(r"\r\n|\r|\n", text)


def find_history_words(text):
    """Return [{line, match, kind}] for every forbidden word in text.

    Line numbers start at 1. An empty list means the text is clean.
    """
    hits = []
    for lineno, line in enumerate(split_lines(text), 1):
        for kind, rx in _HISTORY_RES:
            for m in rx.finditer(line):
                hits.append({"line": lineno, "match": m.group(0),
                             "kind": kind})
    return hits


def check_notes(notes):
    """Check a list of note texts. Return {clean, hits} with per-note hits.

    Each note is a dict with "first_line" and "text". A note with no hits
    is clean. The check never looks at element ids: notes carry none.
    """
    all_hits = []
    for note in notes:
        for hit in find_history_words(note["text"]):
            hit = dict(hit)
            hit["note"] = note["first_line"]
            all_hits.append(hit)
    return {"clean": not all_hits, "hits": all_hits}


def find_note_by_first_line(notes, first_line):
    """Return the note whose first non-empty line equals first_line, or None.

    Notes are found by first line, never by element id. A note that is gone
    returns None: the caller must stop and tell the user, never recreate it
    silently.
    """
    wanted = first_line.strip()
    for note in notes:
        lines = [ln.strip() for ln in split_lines(note["text"]) if ln.strip()]
        if lines and lines[0] == wanted:
            return note
    return None


def renumber_sections(sections, mapping):
    """Renumber sections and update every "see section N" reference.

    sections is a list of {"number", "heading", "body"}. mapping maps an old
    number to its new number. Sections whose number is not in mapping keep
    their number. References to unmapped numbers stay unchanged.

    The rewrite runs in two passes (placeholder, then resolve) so a swap such
    as 1 -> 2, 2 -> 1 cannot cascade: "see section 1" becomes
    "see section 2" and "see section 2" becomes "see section 1", not both 2.
    """
    def remap_text(text):
        spans = []

        def collect(m):
            spans.append(m.group(0))
            return "\x00REF%d\x00" % (len(spans) - 1)

        staged = REF_RE.sub(collect, text)

        def resolve(m):
            idx = int(m.group(1))
            span = spans[idx]

            def remap_num(nm):
                old = int(nm.group(0))
                return str(mapping.get(old, old))

            return NUM_RE.sub(remap_num, span)

        return re.sub(r"\x00REF(\d+)\x00", resolve, staged)

    out = []
    for section in sections:
        number = mapping.get(section["number"], section["number"])
        out.append({"number": number,
                    "heading": remap_text(section["heading"]),
                    "body": remap_text(section["body"])})
    return out


def content_words(text, ignore=None):
    """Return the set of meaning words in text, without format tokens."""
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    words -= FORMAT_WORDS
    if ignore:
        words -= set(w.lower() for w in ignore)
    return words


def word_diff(before, after, ignore=None):
    """Return {added, removed} content words between two versions of a note.

    A rewrite that only changes format (colons, "=" signs, brackets, "ex:",
    new column titles passed as ignore) reports no added and no removed
    words. Any other change reports the words that changed, so a layout
    change cannot silently change a rule.
    """
    old = content_words(before, ignore)
    new = content_words(after, ignore)
    return {"added": sorted(new - old), "removed": sorted(old - new)}

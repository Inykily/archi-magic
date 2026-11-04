# -*- coding: utf-8 -*-
"""READ step for am-shared-text-check (run_query only; it never changes the model).

Pass `workspace` = the absolute path of this skill's `scripts/` folder.

inputs (all optional):
    {"view_name": "Start"}   EVERY view with this name (any view type, not
                              templates), each with its text notes. Reading
                              every match, never only the first match, is
                              what keeps issue board notes from being missed
                              when two views share a name (issue #101).
    {"view_id": 123}         one view with its text notes
    {"all_views": true}      every non-template view with its text notes
    {"note_id": 456}         one note: full text, view id and view name

A view listing gives first lines only, so the agent can pick the notes
to read in full. Read a note in full with note_id, save it to the
scratchpad, then run shared_text_cli.py check on it.

Non-ASCII text is escaped as \\uXXXX (the runtime JSON encoder is ASCII-only in
IronPython). Decode it before you show it.
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import sys

import System
from pyrevit.api import DB

ESCAPE = sys.platform == "cli"
doc = __revit__.ActiveUIDocument.Document  # noqa: F821


def txt(s):
    if not ESCAPE:
        return s
    out = []
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif ord(c) < 128:
            out.append(c)
        else:
            out.append("\\u%04x" % ord(c))
    return "".join(out)


def eid(n):
    return DB.ElementId(System.Int64(int(n)))


def eid_int(element_id):
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def split_lines(text):
    out = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\r":
            if i + 1 < n and text[i + 1] == "\n":
                out.append(text[start:i])
                i += 2
                start = i
            else:
                out.append(text[start:i])
                i += 1
                start = i
        elif c == "\n":
            out.append(text[start:i])
            i += 1
            start = i
        else:
            i += 1
    if start < n or not out:
        out.append(text[start:])
    return out


def view_notes(view):
    notes = []
    for tn in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.TextNote):
        lines = split_lines(tn.Text)
        notes.append({"id": eid_int(tn.Id),
                      "first_line": txt(lines[0] if lines else ""),
                      "paragraphs": len(lines)})
    return {"id": eid_int(view.Id), "name": txt(view.Name),
            "type": str(view.ViewType), "text_notes": notes}


def find_views():
    if inputs.get("view_id"):  # noqa: F821
        v = doc.GetElement(eid(inputs["view_id"]))  # noqa: F821
        return [v] if v is not None and isinstance(v, DB.View) else []
    if inputs.get("all_views"):  # noqa: F821
        return [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
                if not v.IsTemplate]
    name = (inputs.get("view_name") or "").strip().lower()  # noqa: F821
    if not name:
        return []
    return [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
            if not v.IsTemplate and v.Name.strip().lower() == name]


result = {}

if inputs.get("view_id") or inputs.get("view_name") or inputs.get("all_views"):  # noqa: F821
    result["views"] = [view_notes(v) for v in find_views()]

if inputs.get("note_id"):  # noqa: F821
    note = doc.GetElement(eid(inputs["note_id"]))  # noqa: F821
    if note is None or not isinstance(note, DB.TextNote):
        result["note"] = None
    else:
        owner = doc.GetElement(note.OwnerViewId)
        result["note"] = {"id": eid_int(note.Id),
                          "view_id": eid_int(note.OwnerViewId),
                          "view": txt(owner.Name) if owner is not None else "",
                          "text": txt(note.GetFormattedText().GetPlainText())}

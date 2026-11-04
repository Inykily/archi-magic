# -*- coding: utf-8 -*-
"""RECHECK step for am-issue-board (run_query only; it never changes the model).

Pass `workspace` = the absolute path of this scripts/ folder, so that
`import issue_board` works.

inputs:
    {"note_id": 456}    read one note and check every element id on it

For each id<number> on the board, the script reports whether the element
still exists in the model. For a Revit link it also reports whether the
link document is loaded; for a CAD link it reports the link symbol name.
The result is a list of suggested comments, not an edit: post a suggestion
with board_cli.py comment (or a batch), after the user agrees.

Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import sys

import System
from pyrevit.api import DB

import issue_board as ib

doc = __revit__.ActiveUIDocument.Document  # noqa: F821


def eid(n):
    return DB.ElementId(System.Int64(int(n)))


def describe(element):
    """(kind, detail) for one element, never raising."""
    try:
        if isinstance(element, DB.RevitLinkInstance):
            try:
                loaded = element.GetLinkDocument() is not None
            except Exception:
                loaded = None
            if loaded is None:
                return "Revit link", "load state unknown"
            return "Revit link", "loaded" if loaded else "unloaded"
    except Exception:
        pass
    try:
        if isinstance(element, DB.ImportInstance):
            try:
                name = element.Symbol.Name
            except Exception:
                name = ""
            return "CAD link", name
    except Exception:
        pass
    try:
        category = element.Category
        if category is not None:
            return "Element", category.Name
    except Exception:
        pass
    try:
        return "Element", element.Name
    except Exception:
        return "Element", ""


result = {}
note = None
if inputs.get("note_id"):  # noqa: F821
    note = doc.GetElement(eid(inputs["note_id"]))  # noqa: F821
if note is None or not isinstance(note, DB.TextNote):
    result["note"] = None
else:
    ft = note.GetFormattedText()
    text = ft.GetPlainText()
    board = ib.parse_board(text)
    checks = []
    for number, ids in sorted(ib.recheck_inventory(board).items()):
        for eid_int in ids:
            try:
                element = doc.GetElement(eid(eid_int))
            except Exception:
                element = None
            if element is None:
                checks.append({"number": number, "id": eid_int, "exists": False,
                               "kind": "", "detail": ""})
            else:
                kind, detail = describe(element)
                checks.append({"number": number, "id": eid_int, "exists": True,
                               "kind": kind, "detail": detail})
    result["note"] = {"id": inputs["note_id"], "checks": checks,  # noqa: F821
                      "suggestions": ib.format_recheck_suggestions(checks)}

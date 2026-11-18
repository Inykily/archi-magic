# -*- coding: utf-8 -*-
"""Re-read elements by element id. Read-only (run_query / --mode=query).

Issue #256: verify a kept change by a fresh read, not by the script's own
counts. Also reads the text of tags and text notes before a change, for
the change-list review.

inputs: {"ids": [123, 456], "parameters": ["Mark", "Comments"]}
    or  {"preview_path": "C:/.../x.preview.json"}  (ids = the preview's key
         column and deletion ids; parameters = its other columns)

Three names are read from the element, not from a parameter:
    "Category" -> the category name
    "Name"     -> the element name
    "Text"     -> IndependentTag.TagText or TextNote.Text
Every other name is read with element.LookupParameter(name), as the raw
stored value: text, integer, double in Revit internal units (feet, square
feet), or an element id as an integer. null when there is no value.

result = {"document", "columns": ["ElementId", <parameters>...],
          "rows": [[id, value, ...], ...], "missing": [ids not found],
          "escaped": bool}
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import io
import json
import sys

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"  # IronPython result encoder is ASCII-only (see read_sheets.py)
MAX_IDS = 5000  # the query budget in am-revit-api-docs


def txt(s):
    if s is None or not ESCAPE:
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


def id_int(element_id):
    try:
        return int(element_id.Value)        # Revit 2024+
    except AttributeError:
        return int(element_id.IntegerValue)  # removed in Revit 2026


try:
    import System

    def eid(n):
        return DB.ElementId(System.Int64(int(n)))
except ImportError:
    def eid(n):
        return DB.ElementId(int(n))


def load_request():
    ids = inputs.get("ids") or []  # noqa: F821
    names = inputs.get("parameters") or []  # noqa: F821
    path = inputs.get("preview_path")  # noqa: F821
    if path:
        with io.open(path, "r", encoding="utf-8-sig") as f:
            preview = json.loads(f.read())
        columns = preview.get("columns") or []
        key = preview.get("keyColumn") or "ElementId"
        k = columns.index(key)
        ids = [row[k] for row in preview.get("after") or []]
        ids += [d.get("id") if isinstance(d, dict) else d for d in preview.get("deletions") or []]
        names = [c for c in columns if c != key]
    clean = []
    for n in ids:
        if int(n) not in clean:
            clean.append(int(n))
    if not clean:
        raise ValueError("inputs needs ids (or a preview_path with rows).")
    if len(clean) > MAX_IDS:
        raise ValueError("%d ids is more than the query budget of %d." % (len(clean), MAX_IDS))
    return clean, list(names)


PSEUDO = ("Category", "Name", "Text")


def pseudo_value(element, name):
    if name == "Category":
        cat = element.Category
        return txt(cat.Name) if cat is not None else None
    if name == "Name":
        try:
            return txt(element.Name)
        except Exception:
            return None
    if name == "Text":
        if isinstance(element, DB.TextNote):
            return txt(element.Text)
        try:
            return txt(element.TagText)
        except Exception:
            return None
    return None


def read_value(element, name):
    if name in PSEUDO:
        return pseudo_value(element, name)
    param = element.LookupParameter(name)
    if param is None:
        return None
    if not param.HasValue:
        return None
    storage = param.StorageType
    if storage == DB.StorageType.Double:
        return float(param.AsDouble())
    if storage == DB.StorageType.Integer:
        return int(param.AsInteger())
    if storage == DB.StorageType.ElementId:
        return id_int(param.AsElementId())
    return txt(param.AsString())


ids, names = load_request()
rows = []
missing = []
for n in ids:
    element = doc.GetElement(eid(n))  # noqa: F821
    if element is None:
        missing.append(n)
        continue
    rows.append([n] + [read_value(element, name) for name in names])

result = {"document": txt(doc.Title), "columns": ["ElementId"] + names,  # noqa: F821
          "rows": rows, "missing": missing, "escaped": ESCAPE}

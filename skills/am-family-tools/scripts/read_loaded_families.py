# -*- coding: utf-8 -*-
"""READ step for the library search recipe. Read only (run_query / --mode=query).

Lists the loadable families in the open Revit project and the names of
their types, so a library search can show which results are already in
the model. It changes nothing and writes no files.

inputs (all optional):
  {"max_families": 3000,   # families returned
   "max_types": 20000}     # type names returned in total

result = {"document": <title>, "family_count": n, "type_count": n,
          "truncated": bool, "escaped": bool,
          "families": [{"name", "category", "in_place", "types": [name, ...]}]}
or {"error": "no_project_document", ...} when a family document is active.

Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import sys

try:
    from pyrevit.api import DB
except Exception:
    DB = None

try:
    DOC = doc  # noqa: F821  (injected by the agent runtime)
except NameError:
    DOC = None

try:
    INPUTS = inputs  # noqa: F821  (injected by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}

# The agent runtime's IronPython JSON encoder fails on non-ASCII text.
# Under IronPython, escape text to ASCII ("\\" -> "\\\\", e-acute -> "\\u00e9")
# and set "escaped": true. family_index.unescape() reverses it.
ESCAPE = sys.platform == "cli"


def txt(value):
    if value is None:
        return None
    if not ESCAPE:
        return value
    out = []
    for c in value:
        if c == "\\":
            out.append("\\\\")
        elif ord(c) < 128:
            out.append(c)
        else:
            out.append("\\u%04x" % ord(c))
    return "".join(out)


def element_name(element):
    """Element name; element.Name raises on some IronPython types."""
    if DB is not None:
        try:
            return DB.Element.Name.GetValue(element)
        except Exception:
            pass
    try:
        return element.Name
    except Exception:
        return None


def category_name(family):
    try:
        category = family.FamilyCategory
        return category.Name if category is not None else None
    except Exception:
        return None


def read_families(document, families, max_families, max_types):
    """Rows for the given Family elements, sorted by name, within the limits."""
    rows = []
    type_count = 0
    truncated = False
    ordered = sorted(families, key=lambda f: (element_name(f) or "").lower())
    for family in ordered:
        if len(rows) >= max_families:
            truncated = True
            break
        names = []
        for symbol_id in family.GetFamilySymbolIds():
            if type_count >= max_types:
                truncated = True
                break
            symbol = document.GetElement(symbol_id)
            name = element_name(symbol) if symbol is not None else None
            if name is not None:
                names.append(txt(name))
                type_count += 1
        names.sort(key=lambda n: n.lower())
        rows.append({
            "name": txt(element_name(family)),
            "category": txt(category_name(family)),
            "in_place": bool(getattr(family, "IsInPlace", False)),
            "types": names,
        })
        if truncated:
            break
    return {"family_count": len(rows), "type_count": type_count,
            "truncated": truncated, "families": rows}


def run(document, options):
    if document is None or document.IsFamilyDocument:
        return {"error": "no_project_document",
                "message": "Open a project model (not a family) and run again."}
    max_families = int(options.get("max_families", 3000))
    max_types = int(options.get("max_types", 20000))
    families = DB.FilteredElementCollector(document).OfClass(DB.Family).ToElements()
    data = read_families(document, families, max_families, max_types)
    data["document"] = txt(document.Title)
    data["escaped"] = ESCAPE
    return data


if DOC is not None and DB is not None:
    result = run(DOC, INPUTS)

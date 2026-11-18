# -*- coding: utf-8 -*-
"""Tests for scripts/read_loaded_families.py outside Revit.

The script runs inside Revit through run_query. Its imports are guarded,
so CPython can load it and test the pure part with fake elements.
"""
import importlib.util
import io
import os
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")


def load():
    spec = importlib.util.spec_from_file_location(
        "read_loaded_families", os.path.join(SCRIPTS, "read_loaded_families.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCategory(object):
    def __init__(self, name):
        self.Name = name


class FakeSymbol(object):
    def __init__(self, name):
        self.Name = name


class FakeFamily(object):
    def __init__(self, name, category, symbols, in_place=False):
        self.Name = name
        self.FamilyCategory = FakeCategory(category) if category else None
        self.IsInPlace = in_place
        self._ids = list(symbols)

    def GetFamilySymbolIds(self):
        return self._ids


class FakeDocument(object):
    IsFamilyDocument = False
    Title = "Project A"

    def __init__(self, symbols):
        self.symbols = symbols

    def GetElement(self, element_id):
        return self.symbols.get(element_id)


def fixture():
    symbols = {1: FakeSymbol("900 x 2100mm"), 2: FakeSymbol("1000 x 2100mm"), 3: FakeSymbol("Default")}
    families = [FakeFamily("Single Door", "Doors", [2, 1]), FakeFamily("Desk", "Furniture", [3]),
                FakeFamily("Custom Wall Sweep", None, [], in_place=True)]
    return FakeDocument(symbols), families


def test_loads_outside_revit_without_running():
    module = load()
    assert module.DB is None and module.DOC is None
    assert not hasattr(module, "result")


def test_reads_families_sorted_with_type_names():
    module = load()
    document, families = fixture()
    data = module.read_families(document, families, 100, 100)
    assert [f["name"] for f in data["families"]] == ["Custom Wall Sweep", "Desk", "Single Door"]
    door = data["families"][2]
    assert door == {"name": "Single Door", "category": "Doors", "in_place": False,
                    "types": ["1000 x 2100mm", "900 x 2100mm"]}
    assert data["families"][0]["category"] is None and data["families"][0]["in_place"] is True
    assert data["type_count"] == 3 and data["truncated"] is False


def test_limits_mark_the_read_truncated():
    module = load()
    document, families = fixture()
    assert module.read_families(document, families, 1, 100)["truncated"] is True
    limited = module.read_families(document, families, 100, 2)
    assert limited["truncated"] is True and limited["type_count"] == 2


def test_family_document_is_refused():
    module = load()
    document, _ = fixture()
    document.IsFamilyDocument = True
    assert module.run(document, {})["error"] == "no_project_document"
    assert module.run(None, {})["error"] == "no_project_document"


def test_ascii_escape_for_ironpython():
    module = load()
    module.ESCAPE = True
    assert module.txt(u"Caf\u00e9 \\ A") == "Caf\\u00e9 \\\\ A"
    assert module.txt(None) is None


def test_scripts_have_no_f_strings():
    """The skill's scripts keep IronPython 2.7 syntax: no f-strings."""
    fstring_start = getattr(tokenize, "FSTRING_START", None)
    paths = []
    for folder in (SCRIPTS, os.path.join(SCRIPTS, "lib")):
        paths.extend(os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".py"))
    assert len(paths) >= 4
    for path in paths:
        with io.open(path, "rb") as f:
            for token in tokenize.tokenize(f.readline):
                assert token.type != fstring_start or fstring_start is None, path
                if token.type == tokenize.STRING:
                    prefix = token.string[:token.string.find(token.string.lstrip("rRbBuUfF")[0])]
                    assert "f" not in prefix.lower(), "%s: %s" % (path, token.string[:20])

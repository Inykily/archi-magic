# -*- coding: utf-8 -*-
"""Tests for the instance-flag recipe (issue #250): scripts/lib/instance_flag.py,
scripts/instance_flag_preview.py and scripts/apply_instance_flag.py (with a fake Revit).

Run either way:
    python -m pytest skills/am-safe-change/tests -q
    python skills/am-safe-change/tests/test_instance_flag.py
"""
import importlib.util
import io
import json
import os
import runpy
import sys
import tempfile
from types import SimpleNamespace as NS

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))

import instance_flag as fl  # noqa: E402

RUN = "2026-11-18 14:30"


def read(elements, exists=True):
    return {"parameter": "QA Flag", "parameter_exists": exists, "categories": ["OST_Walls"],
            "elements": elements}


def el(eid, amount=None, current=None, status="NotOwned", owner=""):
    return {"id": eid, "category": "Walls", "name": "<type>", "amount": amount,
            "current": current, "status": status, "owner": owner}


# --- pure -----------------------------------------------------------------


def test_format_is_compact_with_run_time():
    assert fl.format_flag("OVER", 0.75, RUN) == "OVER +0.75 @2026-11-18 14:30"
    assert fl.format_flag("OVER", 0.75, RUN, decimals=1, unit=" in", scale=12) == \
        "OVER +9.0 in @2026-11-18 14:30"


@pytest.mark.parametrize("flag,run_time", [("over", RUN), ("OVER LIMIT", RUN), ("OVER", "2026-11-18")])
def test_format_rejects_bad_flag_or_time(flag, run_time):
    with pytest.raises(ValueError):
        fl.format_flag(flag, 1, run_time)


def test_parse_finds_values_of_any_earlier_run():
    assert fl.parse_flag("OVER +1.25 @2026-10-01 09:05") == {
        "flag": "OVER", "amount": "1.25", "time": "2026-10-01 09:05"}
    assert fl.parse_flag("OVER: 12'-0\" > limit") is None
    assert fl.parse_flag("") is None


def test_plan_sets_clears_keeps_and_skips():
    p = fl.plan_flags(read([
        el(1, amount=0.5),                                            # new flag
        el(2, amount=None, current="OVER +0.20 @2026-10-01 09:05"),   # passes now: clear
        el(3, amount=None),                                           # passes, empty: no row
        el(4, amount=0.5, current="OVER +0.50 @2026-11-18 14:30"),    # same value: unchanged
        el(5, amount=1.0, status="OwnedByOtherUser", owner="jdoe"),   # borrowed: skip
        el(6, amount=0.25, current="OVER +0.10 @2026-10-01 09:05"),   # new amount
    ]), "OVER", RUN)
    assert p["steps"] == [
        {"id": 1, "before": "", "after": "OVER +0.50 @2026-11-18 14:30"},
        {"id": 2, "before": "OVER +0.20 @2026-10-01 09:05", "after": ""},
        {"id": 6, "before": "OVER +0.10 @2026-10-01 09:05", "after": "OVER +0.25 @2026-11-18 14:30"}]
    assert p["counts"] == {"set": 2, "cleared": 1, "unchanged": 1, "skipped": 1, "passing": 1}
    assert p["skipped"] == [{"id": 5, "owner": "jdoe", "wanted": "OVER +1.00 @2026-11-18 14:30"}]
    assert not p["blocked"]
    assert p["params"]["create_parameter"] is False
    assert p["ownership_ids"] == [1, 2, 6]
    assert p["before"][0] == [1, "Walls", "<type>", ""]


def test_other_text_in_the_parameter_blocks():
    p = fl.plan_flags(read([el(1, amount=0.5, current="checked by hand")]), "OVER", RUN)
    assert p["blocked"] and p["steps"] == []
    assert "holds other text" in p["warnings"][0]["text"]


def test_missing_parameter_is_created_and_noted():
    p = fl.plan_flags(read([el(1, amount=0.5)], exists=False), "OVER", RUN)
    assert p["params"]["create_parameter"] is True
    assert any("temporary shared parameter file" in n for n in p["notes"])


def test_compare_and_text_table():
    p = fl.plan_flags(read([el(1, amount=0.5), el(2, amount=0.1)]), "OVER", RUN)
    assert fl.compare(p, [[1, "OVER +0.50 @2026-11-18 14:30"], [2, "OVER +0.10 @2026-11-18 14:30"]]) == []
    diffs = fl.compare(p, [[1, ""], [9, "x"]])
    assert diffs == ["1: expected 'OVER +0.50 @2026-11-18 14:30', got ''", "2: not in the result",
                     "9: changed, but not in the preview"]
    assert "2 set, 0 cleared" in fl.text_table(p)


def test_cli_compute(capsys):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "read.json")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"result": read([el(1, amount=0.5)])}))
    spec = importlib.util.spec_from_file_location("flag_cli", os.path.join(SCRIPTS, "instance_flag_preview.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = os.path.join(tmp, "p.json")
    assert mod.main(["compute", "--read", path, "--flag", "OVER", "--run-time", RUN, "--out", out]) == 0
    assert "OVER +0.50" in capsys.readouterr().out
    actual = os.path.join(tmp, "a.json")
    with io.open(actual, "w", encoding="utf-8") as f:
        f.write(json.dumps({"result": {"rows": [[1, "OVER +0.50 @2026-11-18 14:30"]],
                                       "shared_parameter_file_restored": False,
                                       "shared_parameter_file": "x.txt"}}))
    assert mod.main(["compare", "--preview", out, "--actual", actual]) == 1
    assert "NOT restored" in capsys.readouterr().out


# --- apply script with a fake Revit ---------------------------------------


class Id(object):
    def __init__(self, value):
        self.Value = int(value)


class Param(object):
    def __init__(self, value=""):
        self.value = value
        self.IsReadOnly = False

    def AsString(self):
        return self.value

    def Set(self, value):
        self.value = value


class Element(object):
    def __init__(self, doc, eid, value=""):
        self.doc, self.Id, self.param = doc, Id(eid), Param(value)

    def LookupParameter(self, name):
        return self.param if name in self.doc.bound else None


class BindingIterator(object):
    def __init__(self, keys):
        self.keys, self.i = keys, -1

    def Reset(self):
        self.i = -1

    def MoveNext(self):
        self.i += 1
        return self.i < len(self.keys)

    @property
    def Key(self):
        return self.keys[self.i]


class Bindings(object):
    def __init__(self, doc):
        self.doc = doc

    def ForwardIterator(self):
        return BindingIterator([NS(Name=n) for n in sorted(self.doc.bound)])

    def Insert(self, definition, binding, group):
        self.doc.bound.add(definition.Name)
        self.doc.inserted.append((definition.Name, binding, group))
        return True


class App(object):
    def __init__(self, doc, original):
        self.doc = doc
        self.SharedParametersFilename = original
        self.opened = []
        self.Create = NS(NewCategorySet=lambda: CategorySet(), NewInstanceBinding=lambda cats: ("instance", cats))

    def OpenSharedParameterFile(self):
        path = self.SharedParametersFilename
        assert os.path.isfile(path) and os.path.dirname(path) == tempfile.gettempdir()
        self.opened.append(path)
        doc = self.doc

        def create_definition(options):
            definition = NS(Name=options.name, GUID="guid-1")
            doc.definitions[definition.GUID] = definition
            return definition
        return NS(Groups=NS(Create=lambda name: NS(Definitions=NS(Create=create_definition))))


class CategorySet(list):
    def Insert(self, item):
        self.append(item)


class Document(object):
    def __init__(self, original="C:/team/shared-params.txt", bound=(), values=None):
        self.bound = set(bound)
        self.inserted, self.definitions, self.vary = [], {}, []
        self.Application = App(self, original)
        self.ParameterBindings = Bindings(self)
        self.IsWorkshared = False
        self.elements = dict((i, Element(self, i, v)) for i, v in (values or {1: "", 2: ""}).items())
        self.transactions = []
        self.category_ok = True

    def GetElement(self, element_id):
        return self.elements.get(element_id.Value)

    def Regenerate(self):
        pass


class Transaction(object):
    def __init__(self, doc, name):
        self.doc, self.name, self.state = doc, name, None
        doc.transactions.append(self)

    def Start(self):
        self.state = "started"

    def Commit(self):
        self.state = "committed"

    def RollBack(self):
        self.state = "rolled back"

    def HasStarted(self):
        return self.state is not None

    def HasEnded(self):
        return self.state in ("committed", "rolled back")


class Options(object):
    def __init__(self, name, spec):
        self.name, self.spec, self.Visible = name, spec, False


@pytest.fixture
def fake(monkeypatch):
    def make(**kw):
        doc = Document(**kw)

        def get_category(document, bic):
            if not doc.category_ok:
                return None
            return NS(AllowsBoundParameters=True, Name=bic)

        def lookup(document, guid):
            definition = doc.definitions.get(guid)
            internal = NS(SetAllowVaryBetweenGroups=lambda d, flag: doc.vary.append((definition.Name, flag)))
            return NS(GetDefinition=lambda: internal)

        db = NS(ElementId=Id, Transaction=Transaction, ExternalDefinitionCreationOptions=Options,
                SpecTypeId=NS(String=NS(Text="text")), GroupTypeId=NS(Data="data"),
                Category=NS(GetCategory=get_category), BuiltInCategory=NS(OST_Walls="OST_Walls"),
                SharedParameterElement=NS(Lookup=lookup),
                WorksharingUtils=NS(GetCheckoutStatus=lambda d, i: "NotOwned"))
        monkeypatch.setitem(sys.modules, "System", NS(Int64=int))
        monkeypatch.setitem(sys.modules, "pyrevit", NS(api=NS(DB=db)))
        monkeypatch.setitem(sys.modules, "pyrevit.api", NS(DB=db))

        def run(preview):
            return runpy.run_path(os.path.join(SCRIPTS, "apply_instance_flag.py"),
                                  init_globals={"doc": doc, "inputs": {"preview": preview}})["result"]
        return doc, run
    return make


def flag_preview(exists):
    return fl.plan_flags(read([el(1, amount=0.5), el(2, amount=0.25)], exists=exists), "OVER", RUN)


def test_apply_creates_the_parameter_and_restores_the_setting(fake):
    doc, run = fake()
    result = run(flag_preview(exists=False))
    assert result["created_parameter"] is True
    assert result["rows"] == [[1, "OVER +0.50 @2026-11-18 14:30"], [2, "OVER +0.25 @2026-11-18 14:30"]]
    assert doc.Application.SharedParametersFilename == "C:/team/shared-params.txt"
    assert result["shared_parameter_file_restored"] is True
    assert doc.inserted[0][0] == "QA Flag" and doc.inserted[0][2] == "data"
    assert doc.vary == [("QA Flag", True)]
    assert not os.path.exists(doc.Application.opened[0])  # the temporary file is gone
    assert doc.transactions[0].state == "committed"


def test_apply_restores_the_setting_when_creation_fails(fake):
    doc, run = fake(original="")
    doc.category_ok = False
    with pytest.raises(ValueError):
        run(flag_preview(exists=False))
    assert doc.Application.SharedParametersFilename == ""
    assert doc.transactions[0].state == "rolled back"
    assert not os.path.exists(doc.Application.opened[0])
    assert doc.elements[1].param.value == ""


def test_apply_stops_when_a_value_changed_since_the_preview(fake):
    doc, run = fake(bound=["QA Flag"], values={1: "", 2: "edited by hand"})
    with pytest.raises(ValueError) as err:
        run(flag_preview(exists=True))
    assert "Model changed since the preview" in str(err.value)
    assert doc.transactions[0].state == "rolled back"
    assert doc.Application.opened == []  # nothing created


def test_apply_stops_when_the_parameter_appeared(fake):
    doc, run = fake(bound=["QA Flag"])
    with pytest.raises(ValueError) as err:
        run(flag_preview(exists=False))
    assert "now exists" in str(err.value)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

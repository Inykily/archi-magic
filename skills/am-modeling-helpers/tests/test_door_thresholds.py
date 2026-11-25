# -*- coding: utf-8 -*-
"""Tests for the door threshold plan (issue #299): lib/door_thresholds.py,
door_threshold_plan.py and read_door_thresholds.py with a fake Revit."""
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))
sys.path.insert(0, str(SCRIPTS))

import door_thresholds as dt  # noqa: E402
import door_threshold_plan as cli  # noqa: E402

MAP = {"confirmed": True, "codes": {"CPT": ["carpet"], "TZ": ["terrazzo", "tz"], "RF": "rubber",
                                    "PC": ["polished concrete"]}}


def room(rid, finish):
    return {"id": rid, "number": str(rid), "name": "Room", "finish": finish}


def door(did, a, b, sill=None, **extra):
    row = {"id": did, "mark": "D%d" % did, "level": "Level 1", "sill": sill, "sill_found": True,
           "sill_read_only": False, "from_room": a, "to_room": b}
    row.update(extra)
    return row


def sample_read():
    details = [
        {"sheet_number": "A-501", "detail_number": "1", "view_name": "Carpet to Terrazzo Transition"},
        {"sheet_number": "A-501", "detail_number": "2", "view_name": "TERRAZZO / RUBBER"},
        {"sheet_number": "A-502", "detail_number": "3", "view_name": "Rubber - Terrazzo (alt)"},
        {"sheet_number": "A-502", "detail_number": "4", "view_name": "Polished Concrete to Carpet"},
        {"sheet_number": "A-502", "detail_number": "5", "view_name": "Typical Threshold"},
    ]
    doors = [
        door(1, room(101, "TZ"), room(102, "cpt")),         # match, reversed order
        door(2, room(103, "CPT"), room(104, "TZ")),         # match
        door(3, room(105, "RF"), room(106, "TZ")),          # two details
        door(4, room(107, "CPT / RF"), room(108, "TZ")),    # mixed
        door(5, room(109, "-"), room(110, "TZ")),           # empty
        door(6, None, room(111, "TZ")),                     # outside door
        door(7, room(112, "TZ"), room(113, "TZ")),          # same finish
        door(8, room(114, "CPT"), room(115, "TZ"), sill="9/A-509"),  # already filled
        door(9, room(116, "XX"), room(117, "TZ")),          # unknown code
        door(10, room(118, "RF"), room(119, "CPT")),        # no detail
        door(11, room(120, "CPT"), room(121, "TZ"), sill_read_only=True),
        door(12, room(122, "PC"), room(123, "CPT")),        # two-word finish name
        door(13, None, None),
        door(14, room(124, "CPT"), room(125, "TZ"), sill_found=False),
    ]
    return {"kind": dt.READ_KIND, "sill_parameter": "SILL", "finish_parameter": "Floor Finish",
            "phase": {"id": 1, "name": "New Construction"}, "doors": doors, "details": details,
            "missing": [], "complete": True}


def test_split_finishes():
    assert dt.split_finishes("cpt / TZ, rf") == ["CPT", "TZ", "RF"]
    assert dt.split_finishes(" - ") == [] and dt.split_finishes(None) == [] and dt.split_finishes("") == []
    assert dt.split_finishes("CPT/CPT") == ["CPT"]


def test_detail_names_give_order_free_pairs():
    fmap = dt.load_map(MAP)
    assert dt.codes_in_name("Carpet to Terrazzo Transition", fmap) == ["CPT", "TZ"]
    assert dt.codes_in_name("TZ-RF", fmap) == ["TZ"]  # "rf" is not a word for RF
    assert dt.codes_in_name("Carpeted", fmap) == []  # whole words only
    rows, index = dt.parse_details(sample_read()["details"], fmap)
    assert index["CPT|TZ"] == ["1/A-501"]
    assert index["RF|TZ"] == ["2/A-501", "3/A-502"]
    assert index["CPT|PC"] == ["4/A-502"]
    assert rows[4]["pair"] is None
    assert dt.pair_key("TZ", "CPT") == dt.pair_key("CPT", "TZ")


def test_manual_pair_and_format():
    fmap = dt.load_map(dict(MAP, details={"A-502-5": ["CPT", "RF"]}))
    rows, index = dt.parse_details(sample_read()["details"], fmap, "{sheet}-{detail}")
    assert index["CPT|RF"] == ["A-502-5"] and rows[4]["source"] == "manual"
    with pytest.raises(dt.MapError):
        dt.load_map({"codes": {}})
    with pytest.raises(dt.MapError):
        dt.load_map({"codes": {"CPT": "carpet"}, "details": {"1/A": ["CPT"]}})


def test_analyse_statuses():
    analysis = dt.analyse(sample_read(), dt.load_map(MAP))
    status = dict((d["id"], d["status"]) for d in analysis["doors"])
    assert status == {1: dt.MATCH, 2: dt.MATCH, 3: dt.AMBIGUOUS, 4: dt.MIXED, 5: dt.EMPTY,
                      6: dt.EXTERIOR, 7: dt.SAME, 8: dt.HAS_VALUE, 9: dt.UNKNOWN_CODE,
                      10: dt.NO_MATCH, 11: dt.READ_ONLY, 12: dt.MATCH, 13: dt.NO_ROOMS,
                      14: dt.NO_PARAMETER}
    texts = " ".join(w["text"] for w in analysis["warnings"])
    assert "XX" in texts and "Typical Threshold" in texts and "RF|TZ has 2 details" in texts
    assert not any(w["blocking"] for w in analysis["warnings"])


def test_preview_writes_only_clear_matches():
    preview = dt.build_preview(dt.analyse(sample_read(), dt.load_map(MAP)))
    assert preview["blocked"] is False
    assert preview["columns"] == ["ElementId", "Mark", "SILL"]
    assert preview["after"] == [[1, "D1", "1/A-501"], [2, "D2", "1/A-501"], [12, "D12", "4/A-502"]]
    assert [s["element_id"] for s in preview["steps"]] == [1, 2, 12]
    assert preview["steps"][0]["expect_before"] == ""
    assert preview["ownership_ids"] == [1, 2, 12]
    assert "3 of 14 doors get a sill value" in preview["notes"][0]
    assert len(preview["not_changed"]) == 11


def test_unconfirmed_map_blocks_the_preview():
    preview = dt.build_preview(dt.analyse(sample_read(), dt.load_map(dict(MAP, confirmed=False))))
    assert preview["blocked"] is True and preview["steps"] == []


def test_cli(tmp_path, capsys):
    read_p, map_p, out_p = tmp_path / "doors.json", tmp_path / "map.json", tmp_path / "preview.json"
    read_p.write_text(json.dumps({"payload": json.dumps(sample_read())}))
    map_p.write_text(json.dumps(MAP))
    assert cli.main(["report", "--read", str(read_p), "--map", str(map_p),
                     "--out", str(tmp_path / "a.json")]) == 0
    assert "more_than_one_match 1" in capsys.readouterr().out
    assert cli.main(["preview", "--read", str(read_p), "--map", str(map_p), "--out", str(out_p)]) == 0
    assert json.loads(out_p.read_text())["kind"] == "change-preview"
    map_p.write_text(json.dumps(dict(MAP, confirmed=False)))
    assert cli.main(["preview", "--read", str(read_p), "--map", str(map_p), "--out", str(out_p)]) == 1
    map_p.write_text("{}")
    assert cli.main(["report", "--read", str(read_p), "--map", str(map_p)]) == 2


# ------------------------------------------------------------ fake Revit

class Id(object):
    def __init__(self, value):
        self.Value = value


class Param(object):
    StorageType = "String"

    def __init__(self, value, read_only=False):
        self.value, self.IsReadOnly = value, read_only

    def AsString(self):
        return self.value

    def AsValueString(self):
        return self.value


class Element(object):
    def __init__(self, eid, params=None, lookup=None, **extra):
        self.Id, self.params, self.lookup = Id(eid), params or {}, lookup or {}
        self.__dict__.update(extra)

    def get_Parameter(self, bip):
        return self.params.get(bip)

    def LookupParameter(self, name):
        return self.lookup.get(name)


class ViewSheet(Element):
    def GetAllViewports(self):
        return [Id(v) for v in self.viewports]


class Doc(object):
    IsFamilyDocument, Title = False, "Project A"

    def __init__(self, elements, phases):
        self.elements, self.Phases = elements, phases

    def GetElement(self, element_id):
        return self.elements.get(element_id.Value)


def test_read_script_with_fake_revit(monkeypatch):
    bip = NS(ROOM_NUMBER="num", ROOM_NAME="name", VIEWPORT_DETAIL_NUMBER="detail", ALL_MODEL_MARK="mark")
    phase_a, phase_b = Element(1, Name="Existing"), Element(2, Name="New Construction")
    r1 = Element(101, {"num": Param("101"), "name": Param("Lobby")}, {"Floor Finish": Param("TZ")})
    r2 = Element(102, {"num": Param("102"), "name": Param("Office")}, {"Floor Finish": Param("CPT")})
    seen = []

    def from_room(phase):
        seen.append(phase.Name)
        return r1

    d = Element(500, {"mark": Param("D1")}, {"SILL": Param("")}, LevelId=Id(30),
                get_FromRoom=from_room, get_ToRoom=lambda phase: r2)
    outside = Element(501, {"mark": Param("D2")}, {}, LevelId=Id(30),
                      get_FromRoom=lambda phase: None, get_ToRoom=lambda phase: r1)
    view = Element(700, Name="Carpet to Terrazzo")
    vp = Element(600, {"detail": Param("1")}, ViewId=Id(700))
    sheet = ViewSheet(800, SheetNumber="A-501", viewports=[600])
    doc = Doc({500: d, 501: outside, 600: vp, 700: view, 800: sheet, 30: Element(30, Name="Level 1")},
              [phase_a, phase_b])

    class Collector(object):
        def __init__(self, doc):
            pass

        def OfCategory(self, _):
            return self

        def WhereElementIsNotElementType(self):
            return iter([d, outside])

    db = NS(BuiltInParameter=bip, BuiltInCategory=NS(OST_Doors="doors"), ViewSheet=ViewSheet,
            StorageType=NS(String="String"), ElementId=lambda n: Id(n), FilteredElementCollector=Collector)
    monkeypatch.setitem(sys.modules, "pyrevit", NS(api=NS(DB=db)))
    monkeypatch.setitem(sys.modules, "pyrevit.api", NS(DB=db))
    monkeypatch.setitem(sys.modules, "System", NS(Int64=int))
    out = runpy.run_path(str(SCRIPTS / "read_door_thresholds.py"),
                         init_globals={"doc": doc, "inputs": {"sill_parameter": "SILL", "sheet_ids": [800, 9]}})
    report = json.loads(out["result"]["payload"])
    assert report["phase"]["name"] == "New Construction" and seen == ["New Construction"]
    assert report["details"] == [{"sheet_id": 800, "sheet_number": "A-501", "view_id": 700,
                                  "view_name": "Carpet to Terrazzo", "detail_number": "1"}]
    assert report["missing"] == [9]
    first, second = report["doors"]
    assert first["from_room"]["finish"] == "TZ" and first["to_room"]["number"] == "102"
    assert first["sill"] == "" and first["sill_found"] is True
    assert second["sill_found"] is False and second["from_room"] is None
    analysis = dt.analyse(report, dt.load_map(MAP))
    assert analysis["doors"][0]["refs"] == ["1/A-501"]
    bad = runpy.run_path(str(SCRIPTS / "read_door_thresholds.py"),
                         init_globals={"doc": doc, "inputs": {"sheet_ids": [800]}})
    assert json.loads(bad["result"]["payload"])["error"] == "bad_inputs"

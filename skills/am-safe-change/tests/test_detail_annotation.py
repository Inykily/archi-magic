# -*- coding: utf-8 -*-
"""Tests for the detail-annotation recipe (issue #298): scripts/lib/detail_annotation.py,
scripts/detail_annotation_preview.py, and the read and apply scripts with a fake Revit.

Run: python -m pytest skills/am-safe-change/tests -q
"""
import base64
import json
import os
import runpy
import struct
import sys
import zlib
from types import SimpleNamespace as NS

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))
sys.path.insert(0, SCRIPTS)

import detail_annotation as da  # noqa: E402
import detail_annotation_preview as cli  # noqa: E402
import run_checks  # noqa: E402
import side_effects as se  # noqa: E402

CROP = {"min": [-2.0, -1.0], "max": [2.0, 1.0]}


def frame_view(vid, name, **extra):
    view = {"id": vid, "name": name, "scale": 3, "view_type": "Detail",
            "origin": [10.0, 20.0, 0.0], "right": [1.0, 0.0, 0.0], "up": [0.0, 0.0, 1.0],
            "crop_uv": CROP, "filled_regions": [], "detail_lines": [], "text_notes": []}
    view.update(extra)
    return view


def sample_read():
    reference = frame_view(
        200, "Transition 1",
        filled_regions=[{"id": 301, "type_id": 11, "type_name": "Finish A",
                         "loops": [[[-1.0, 0.0], [0.0, 0.0], [0.0, 0.1], [-1.0, 0.1]]]}],
        detail_lines=[{"id": 302, "style_id": 21, "style_name": "Thin", "start": [0.0, 0.0],
                       "end": [0.0, 0.1]},
                      {"id": 303, "style_id": 21, "style_name": "Thin", "start": [0.1, 0.0],
                       "end": [0.1, 0.1]}],
        text_notes=[{"id": 304, "type_id": 31, "type_name": "Note 3/32", "text": "FINISH A",
                     "coord": [-0.5, 0.6], "align": "Center", "leader_left": "TopLine",
                     "leaders": [{"end": [-0.5, 0.05], "elbow": [-0.5, 0.5], "anchor": [-0.5, 0.55]}]}])
    empty_ref = frame_view(201, "Unfinished")
    target = frame_view(100, "Transition 2")
    return {"kind": da.READ_KIND, "document": "Project A", "target_view_id": 100,
            "views": [target, reference, empty_ref],
            "filled_region_types": [{"id": 11, "name": "Finish A"}, {"id": 12, "name": "Finish B"}],
            "line_styles": [{"id": 21, "name": "Thin"}, {"id": 22, "name": "Wide"}],
            "text_note_types": [{"id": 31, "name": "Note 3/32"}], "missing": [], "escaped": False}


def sample_plan():
    return {"view_id": 100,
            "copy": [{"from_view_id": 200, "ids": [302, 303], "offset": [0.5, 0.0]}],
            "items": [{"kind": "filled_region", "type": "Finish B",
                       "loops": [[[0.0, 0.0], [1.0, 0.0], [1.0, 0.1], [0.0, 0.1]]]},
                      {"kind": "text_note", "type": "Note 3/32", "text": "FINISH B",
                       "at": [0.5, 0.6], "leader_end": [0.5, 0.05]}]}


def test_style_summary_picks_the_finished_reference():
    summary = da.style_summary(sample_read(), target_view_id=100)
    assert [r["id"] for r in summary["views"]] == [200, 201]
    assert summary["closest"] == 200
    ref = summary["views"][0]
    assert ref["line_styles"] == [("Thin", 2)]
    assert ref["leader_layouts"] == [("Center / TopLine / 1 leader(s)", 1)]
    assert "Closest finished detail: id 200." in da.style_text(summary)


def test_copy_items_translates_linework_and_skips_text():
    items, warnings = da.copy_items(sample_read(), {"from_view_id": 200, "offset": [1.0, -0.5]})
    assert warnings == []
    assert [i["kind"] for i in items] == ["filled_region", "detail_line", "detail_line"]
    assert items[1]["start"] == [1.0, -0.5] and items[1]["end"] == [1.0, -0.4]
    _items, warnings = da.copy_items(sample_read(), {"from_view_id": 200, "ids": [999]})
    assert warnings[0]["blocking"] is True


def test_compute_plan_builds_steps_in_model_coordinates():
    preview = da.compute_plan(sample_read(), sample_plan())
    assert preview["blocked"] is False
    assert [s["kind"] for s in preview["steps"]] == ["detail_line", "detail_line", "filled_region", "text_note"]
    line = preview["steps"][0]
    assert line["type_id"] == 21 and line["start"] == [0.5, 0.0]
    assert line["start_model"] == [10.5, 20.0, 0.0] and line["end_model"] == [10.5, 20.0, 0.1]
    note = preview["steps"][3]
    assert note["leader_end_model"] == [10.5, 20.0, 0.05]
    assert note["align"] == "Center" and note["leader_left"] == "TopLine"
    assert len(preview["before"]) == len(preview["after"]) == 4
    assert preview["after"][3][4] == "FINISH B"
    assert preview["edited_categories"] == ["Detail Items", "Lines", "Text Notes"]
    assert "<Sketch>" in preview["expected_dependent_categories"]
    assert preview["ownership_ids"] == [100]


def test_compute_plan_blocks_bad_items():
    plan = {"view_id": 100, "items": [
        {"kind": "filled_region", "type": "Missing type", "loops": [[[0, 0], [1, 0]]]},
        {"kind": "detail_line", "style": "Thin", "start": [0, 0], "end": [0, 0]},
        {"kind": "text_note", "type": "Note 3/32", "text": " ", "at": [5.0, 0.0]}]}
    preview = da.compute_plan(sample_read(), plan)
    assert preview["blocked"] is True and preview["steps"] == []
    texts = " ".join(w["text"] for w in preview["warnings"])
    assert "not in the model" in texts and "at least 3 points" in texts
    assert "zero length" in texts and "no text" in texts and "outside the crop" in texts
    assert "BLOCKED" in da.text_table(preview)
    with pytest.raises(da.PlanError):
        da.compute_plan(sample_read(), {"view_id": 999, "items": plan["items"]})


def test_no_filled_region_means_no_sketch_expectation():
    plan = {"view_id": 100, "items": [{"kind": "detail_line", "style": "Thin",
                                       "start": [0, 0], "end": [0.5, 0]}]}
    preview = da.compute_plan(sample_read(), plan)
    assert preview["expected_dependent_categories"] == []
    assert preview["edited_categories"] == ["Lines"]


def test_side_effects_accept_filled_region_sketch_elements():
    preview = da.compute_plan(sample_read(), sample_plan())
    dryrun = {"modified_count": 4 + 18 + 14 + 6,
              "modified_by_category": {"Detail Items": 1, "Lines": 2, "Text Notes": 1,
                                       "<Sketch>": 18, "Automatic Sketch Dimensions": 14,
                                       "(no category)": 6}}
    summary = se.summarize(preview, dryrun, preview["edited_categories"])
    assert summary["unexpected"] == [] and summary["regenerated"] == 38
    run = {"changes": {"by_category": {"added": {"Detail Items": 1, "Lines": 2, "Text Notes": 1,
                                                 "<Sketch>": 18, "Automatic Sketch Dimensions": 14,
                                                 "": 6}}}}
    review = run_checks.review_change_list(run, preview, annotations=[])
    assert review["unexpected"] == []
    assert not [s for s in review["stops"] if "uncategorized" in s or "Unexpected" in s]


def test_mapping_from_points_and_crop():
    mapping, warnings = da.mapping_from_points([0, 0], [100, 200], [1, 1], [150, 150])
    assert warnings == []
    assert da.to_pixel(mapping, [2, -1]) == [200.0, 250.0]
    _m, warnings = da.mapping_from_points([0, 0], [100, 200], [1, 1], [150, 100])
    assert "different x and y scales" in warnings[0]
    with pytest.raises(da.PlanError):
        da.mapping_from_points([0, 0], [0, 0], [0, 1], [0, 10])
    crop_map = da.mapping_from_crop(CROP, 400, 300)
    assert da.to_pixel(crop_map, [-2, 1]) == [0.0, 50.0]
    assert da.to_pixel(crop_map, [2, -1]) == [400.0, 250.0]


def test_svg_and_html_show_every_planned_item():
    preview = da.compute_plan(sample_read(), sample_plan())
    mapping = da.mapping_from_crop(CROP, 800, 400)
    svg = da.svg_overlay(preview, mapping, 800, 400, "data:image/png;base64,AAAA")
    assert svg.count("<line data-step=") == 3  # 2 detail lines + 1 leader
    assert svg.count("<polygon") == 1 and "FINISH B" in svg and "<image" in svg
    page = da.html_page(preview, svg, "note <b>")
    assert page.startswith("<!doctype html>") and "note &lt;b&gt;" in page
    assert "prefers-color-scheme: dark" in page


def tiny_png(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_cli_compute_draw_compare(tmp_path, capsys):
    read_p, plan_p, prev_p = tmp_path / "read.json", tmp_path / "plan.json", tmp_path / "preview.json"
    read_p.write_text(json.dumps({"status": "ok", "result": sample_read()}), encoding="utf-8")
    plan_p.write_text(json.dumps(sample_plan()), encoding="utf-8")
    assert cli.main(["style", "--read", str(read_p), "--view", "100"]) == 0
    assert cli.main(["compute", "--read", str(read_p), "--plan", str(plan_p), "--out", str(prev_p)]) == 0
    png = tmp_path / "view.png"
    png.write_bytes(tiny_png(40, 20))
    html = tmp_path / "drawing.html"
    assert cli.main(["draw", "--preview", str(prev_p), "--out", str(html), "--capture", str(png),
                     "--known", "0,0:20,10", "--known", "1,1:30,0"]) == 0
    text = html.read_text(encoding="utf-8")
    assert "data:image/png;base64," in text and 'viewBox="0 0 40 20"' in text
    assert cli.main(["draw", "--preview", str(prev_p), "--out", str(html)]) == 0
    preview = json.loads(prev_p.read_text(encoding="utf-8"))
    created = []
    for s in preview["steps"]:
        row = {"step": s["step"], "kind": s["kind"], "ids": [900 + s["step"]], "type_id": s["type_id"]}
        if s["kind"] == "filled_region":
            row["loops"] = [list(reversed(s["loops"][0]))]
        elif s["kind"] == "detail_line":
            row["start"], row["end"] = s["end"], s["start"]
        else:
            row.update(text=s["text"], at=s["at"], leader_end=s["leader_end"])
        created.append(row)
    run_p = tmp_path / "run.json"
    run_p.write_text(json.dumps({"result": {"created": created}}), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["compare", "--preview", str(prev_p), "--actual", str(run_p)]) == 0
    assert "MATCHES PREVIEW" in capsys.readouterr().out
    created[3]["text"] = "OTHER"
    created[0]["start"] = [9, 9]
    run_p.write_text(json.dumps({"created": created}), encoding="utf-8")
    assert cli.main(["compare", "--preview", str(prev_p), "--actual", str(run_p)]) == 1
    dry_p = tmp_path / "dry.json"
    dry_p.write_text(json.dumps({"modified_count": 42, "modified_by_category": {
        "Lines": 2, "<Sketch>": 18, "Automatic Sketch Dimensions": 14, "Detail Items": 1,
        "Text Notes": 1, "(no category)": 6}}), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["side-effects", "--preview", str(prev_p), "--dryrun", str(dry_p)]) == 0
    assert "(unexpected)" not in capsys.readouterr().out
    assert cli.main(["compute", "--read", str(plan_p), "--plan", str(plan_p), "--out", str(prev_p)]) == 2


def test_load_read_unescapes_ironpython_text():
    read = sample_read()
    read["escaped"] = True
    read["views"][1]["text_notes"][0]["text"] = "CAF\\u00c9"
    loaded = da.load_read(read)
    assert loaded["views"][1]["text_notes"][0]["text"] == u"CAFÉ"


# ------------------------------------------------------------ fake Revit

class XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = float(x), float(y), float(z)


class Id(object):
    def __init__(self, value):
        self.Value = value


class Line(object):
    def __init__(self, a, b):
        self.a, self.b, self.IsBound = a, b, True

    @staticmethod
    def CreateBound(a, b):
        return Line(a, b)

    def GetEndPoint(self, i):
        return self.a if i == 0 else self.b


class CurveLoop(list):
    Append = list.append


class DotNetList(list):
    Add = list.append


class FilledRegion(object):
    created = []

    def __init__(self, eid, type_id, loops):
        self.Id, self.type_id, self.loops = Id(eid), type_id, loops

    def GetTypeId(self):
        return self.type_id

    def GetBoundaries(self):
        return self.loops

    @classmethod
    def Create(cls, doc, type_id, view_id, loops):
        region = cls(700 + len(cls.created), type_id, list(loops))
        cls.created.append(region)
        return region


class DetailCurve(object):
    def __init__(self, eid, curve, style=None):
        self.Id, self.GeometryCurve, self.LineStyle = Id(eid), curve, style


class Leader(object):
    def __init__(self):
        self.End = None


class TextNote(object):
    def __init__(self, eid, coord, text, type_id, align="Center"):
        self.Id, self.Coord, self.Text, self.type_id = Id(eid), coord, text, type_id
        self.HorizontalAlignment, self.LeaderLeftAttachment = align, "TopLine"
        self.leaders = []

    def GetTypeId(self):
        return self.type_id

    def GetLeaders(self):
        return self.leaders

    def AddLeader(self, kind):
        leader = Leader()
        self.leaders.append(leader)
        return leader

    @staticmethod
    def Create(doc, view_id, at, text, options):
        return TextNote(800, at, text + "\r", options.TypeId, options.HorizontalAlignment)


class View(object):
    IsTemplate, CropBoxActive, Scale, ViewType = False, False, 3, "ViewType.Detail"

    def __init__(self, vid, name):
        self.Id, self.Name = Id(vid), name
        self.Origin, self.RightDirection, self.UpDirection = XYZ(10, 20, 0), XYZ(1, 0, 0), XYZ(0, 0, 1)


class ViewSheet(View):
    pass


class Named(object):
    def __init__(self, eid, name):
        self.Id, self.Name = Id(eid), name


class Transaction(object):
    def __init__(self, doc, title):
        self.state = "new"

    def Start(self):
        self.state = "started"

    def Commit(self):
        self.state = "committed"

    def RollBack(self):
        self.state = "rolled back"

    def HasStarted(self):
        return self.state != "new"

    def HasEnded(self):
        return self.state in ("committed", "rolled back")


def fake_db(collector):
    return NS(XYZ=XYZ, Line=Line, CurveLoop=CurveLoop, FilledRegion=FilledRegion,
              DetailCurve=DetailCurve, TextNote=TextNote, View=View, ViewSheet=ViewSheet,
              ElementId=lambda n: Id(int(n)), Transaction=Transaction,
              FilledRegionType="FilledRegionType", TextNoteType="TextNoteType",
              FilteredElementCollector=collector,
              TextNoteOptions=lambda type_id: NS(TypeId=type_id, HorizontalAlignment=None),
              HorizontalTextAlignment=NS(Center="Center", Left="Left", Right="Right"),
              LeaderAtachement=NS(TopLine="TopLine", Midpoint="Midpoint", BottomLine="BottomLine"),
              TextNoteLeaderTypes=NS(TNLT_STRAIGHT_L="L"),
              BuiltInCategory=NS(OST_Lines="lines"), BuiltInParameter=NS(SYMBOL_NAME_PARAM="n"),
              GraphicsStyleType=NS(Projection="projection"))


class Doc(object):
    IsFamilyDocument, Title = False, "Project A"

    def __init__(self, elements):
        self.elements = elements
        style = NS(Id=Id(21))
        sub = NS(Name="Thin", GetGraphicsStyle=lambda kind: style)
        self.Settings = NS(Categories=NS(get_Item=lambda bic: NS(SubCategories=[sub])))
        self.Create = NS(NewDetailCurve=lambda view, line: DetailCurve(750, line))

    def GetElement(self, element_id):
        return self.elements.get(element_id.Value)

    def Regenerate(self):
        pass


def run_script(monkeypatch, name, db, doc, inputs):
    monkeypatch.setitem(sys.modules, "pyrevit", NS(api=NS(DB=db)))
    monkeypatch.setitem(sys.modules, "pyrevit.api", NS(DB=db))
    monkeypatch.setitem(sys.modules, "System", NS(Int64=int))
    monkeypatch.setitem(sys.modules, "System.Collections.Generic",
                        NS(List=_ListFactory()))
    out = runpy.run_path(os.path.join(SCRIPTS, name), init_globals={"doc": doc, "inputs": inputs})
    return out["result"]


class _ListFactory(object):
    def __getitem__(self, _):
        return DotNetList


def test_read_script_returns_view_coordinates(monkeypatch):
    region = FilledRegion(301, Id(11), [[Line(XYZ(9, 20, 0), XYZ(10, 20, 0)),
                                         Line(XYZ(10, 20, 0), XYZ(10, 20, 0.1)),
                                         Line(XYZ(10, 20, 0.1), XYZ(9, 20, 0))]])
    curve = DetailCurve(302, Line(XYZ(10, 20, 0), XYZ(10, 20, 0.1)), Named(21, "Thin"))
    note = TextNote(304, XYZ(9.5, 20, 0.6), "FINISH A", Id(31))
    leader = Leader()
    leader.End, leader.Elbow, leader.Anchor = XYZ(9.5, 20, 0.05), XYZ(9.5, 20, 0.5), XYZ(9.5, 20, 0.55)
    note.leaders.append(leader)
    view_items = {100: [], 200: [region, curve, note]}

    class Collector(object):
        def __init__(self, doc, view_id=None):
            self.items = view_items.get(view_id.Value, []) if view_id is not None else []
            self.kind = None

        def WhereElementIsNotElementType(self):
            return self

        def OfClass(self, kind):
            self.items = {"FilledRegionType": [Named(11, "Finish A")],
                          "TextNoteType": [Named(31, "Note 3/32")]}[kind]
            return self

        def __iter__(self):
            return iter(self.items)

    doc = Doc({100: View(100, "Target"), 200: View(200, "Reference"), 11: Named(11, "Finish A"),
               31: Named(31, "Note 3/32")})
    result = run_script(monkeypatch, "read_detail_annotation.py", fake_db(Collector), doc,
                        {"view_id": 100, "reference_view_ids": [200, 555]})
    assert result["kind"] == da.READ_KIND and result["missing"] == [555]
    ref = result["views"][1]
    assert ref["filled_regions"][0]["loops"] == [[[-1.0, 0.0], [0.0, 0.0], [0.0, 0.1]]]
    assert ref["detail_lines"][0]["style_name"] == "Thin"
    assert ref["text_notes"][0]["coord"] == [-0.5, 0.6]
    assert ref["text_notes"][0]["leaders"][0]["end"] == [-0.5, 0.05]
    assert result["line_styles"] == [{"id": 21, "name": "Thin"}]
    bad = run_script(monkeypatch, "read_detail_annotation.py", fake_db(Collector), doc, {})
    assert bad["error"] == "bad_inputs"


def test_apply_script_replays_steps_and_rereads(monkeypatch):
    FilledRegion.created = []
    preview = da.compute_plan(sample_read(), sample_plan())
    view = View(100, "Target")
    doc = Doc({100: view, 11: Named(11, "Finish A"), 12: Named(12, "Finish B"),
               21: Named(21, "Thin"), 31: Named(31, "Note 3/32")})
    result = run_script(monkeypatch, "apply_detail_annotation.py", fake_db(None), doc, {"preview": preview})
    assert result["steps_applied"] == 4
    assert da.compare(preview, result) == []
    note = [r for r in result["created"] if r["kind"] == "text_note"][0]
    assert note["text"] == "FINISH B" and note["leader_end"] == [0.5, 0.05]
    view.Origin = XYZ(11, 20, 0)
    with pytest.raises(ValueError, match="Model changed since the preview"):
        run_script(monkeypatch, "apply_detail_annotation.py", fake_db(None), doc, {"preview": preview})

# -*- coding: utf-8 -*-
"""Tests for scripts/lib/run_checks.py and scripts/dry_run_checks.py (issues #256, #255).

Run either way:
    python -m pytest skills/am-safe-change/tests -q
    python skills/am-safe-change/tests/test_dry_run_checks.py
"""
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import run_checks as checks  # noqa: E402

CLI = os.path.join(HERE, "..", "scripts", "dry_run_checks.py")


def plan_view(bottom=0.0, top=7.5, crop=None):
    return {"id": 20, "name": "Level 1 finish plan",
            "view_range": {"bottom": bottom, "top": top}, "crop": crop}


def box(lo, hi):
    return {"min": list(lo), "max": list(hi)}


def element(eid, lo, hi, category="Specialty Equipment", hidden=False):
    return {"id": eid, "category": category, "name": "<family>", "bbox": box(lo, hi),
            "hidden": hidden}


# --- visibility -----------------------------------------------------------


def test_element_two_storeys_up_is_above_the_view_range():
    # Field report: Z given as an offset was added to the level elevation twice.
    rows = checks.visibility_warnings(plan_view(), [
        element(1, (0, 0, 0), (1, 1, 4)),          # on the level: fine
        element(2, (0, 0, 28), (1, 1, 32)),        # about two storeys up
    ])
    assert [r["id"] for r in rows] == [2]
    assert "above the view range" in rows[0]["text"]
    assert "20.50 ft over the top" in rows[0]["text"]


def test_element_below_the_view_depth():
    rows = checks.visibility_warnings(plan_view(bottom=-1.0), [element(3, (0, 0, -9), (1, 1, -5))])
    assert len(rows) == 1 and "below the view range" in rows[0]["text"]


def test_unlimited_view_range_gives_no_range_warning():
    rows = checks.visibility_warnings(plan_view(bottom=None, top=None),
                                      [element(4, (0, 0, 500), (1, 1, 501))])
    assert rows == []


def test_crop_region_uses_the_crop_frame_also_when_rotated():
    # A crop frame turned 90 degrees: local x is world +Y, local y is world -X.
    crop = {"origin": [100, 100, 0], "basis_x": [0, 1, 0], "basis_y": [-1, 0, 0],
            "min": [-10, -10, 0], "max": [10, 10, 0]}
    inside = element(5, (95, 95, 0), (96, 96, 1))
    outside = element(6, (130, 100, 0), (131, 101, 1))
    rows = checks.visibility_warnings(plan_view(crop=crop), [inside, outside])
    assert [r["id"] for r in rows] == [6]
    assert "outside the crop region" in rows[0]["text"]


def test_hidden_and_boxless_elements_are_named():
    rows = checks.visibility_warnings(plan_view(), [
        element(7, (0, 0, 0), (1, 1, 1), hidden=True),
        {"id": 8, "category": "Floors", "name": "", "bbox": None},
    ])
    texts = [r["text"] for r in rows]
    assert any("hidden in view" in t for t in texts)
    assert any("no model box" in t for t in texts)


# --- tags -----------------------------------------------------------------


def tag(tid, text="F-01", host=10, end=None, has_leader=True, host_box=None):
    return {"id": tid, "category": "Keynote Tags", "text": text, "has_leader": has_leader,
            "leader_ends": [end] if end else [], "host_ids": [host],
            "host_boxes": [host_box or box((host, 0, 0), (host + 1, 1, 1))]}


def test_empty_tag_text_and_question_mark_are_warnings():
    rows = checks.tag_text_warnings([tag(1, ""), tag(2, "  "), tag(3, "?"), tag(4, None),
                                     tag(5, "F-01")])
    assert [r["id"] for r in rows] == [1, 2, 3, 4]


def test_leader_end_far_from_its_host():
    near = tag(1, host=10, end=[10.5, 0.5, 0])
    far = tag(2, host=20, end=[40, 0.5, 0])
    rows = checks.leader_warnings([near, far], max_distance=3.0)
    assert [r["id"] for r in rows] == [2]
    assert "19.00 ft from its host" in rows[0]["text"]


def test_copied_tags_that_share_one_leader_end_are_found():
    # Field report: 70 copied tags kept the template tag's leader end.
    end = [5.0, 5.0, 0.0]
    tags = [tag(i, host=100 + i, end=end, host_box=box((0, 0, 0), (10, 10, 1)))
            for i in range(1, 13)]
    rows = checks.leader_warnings(tags, max_distance=50)
    assert len(rows) == 1
    assert rows[0]["text"].startswith("12 tags of different hosts share one leader end")
    assert "and 2 more" in rows[0]["text"]


def test_two_tags_of_one_host_may_share_a_leader_end():
    end = [10.5, 0.5, 0]
    assert checks.leader_warnings([tag(1, host=10, end=end), tag(2, host=10, end=end)]) == []


def test_tag_without_leader_is_not_checked():
    assert checks.leader_warnings([tag(1, has_leader=False, end=[99, 99, 0])]) == []


# --- computed values ------------------------------------------------------


def test_values_read_before_regenerate_are_a_stop():
    rows = checks.value_warnings([{"id": 1, "name": "Area", "value": 0.0}], regenerated=False)
    assert rows[0]["blocking"] is True
    assert "before doc.Regenerate()" in rows[0]["text"]
    assert "reads 0.0" in rows[1]["text"]


def test_zero_and_empty_values_after_regenerate_are_warnings():
    rows = checks.value_warnings([{"id": 1, "name": "Area", "value": 120.5},
                                  {"id": 2, "name": "Area", "value": 0},
                                  {"id": 3, "name": "Length", "value": None}], regenerated=True)
    assert [r["id"] for r in rows] == [2, 3]
    assert not any(r["blocking"] for r in rows)


def test_content_report_counts_and_text():
    content = {"regenerated": True, "view": plan_view(),
               "elements": [element(2, (0, 0, 28), (1, 1, 32))],
               "tags": [tag(9, "")], "values": []}
    report = checks.content_report(content)
    assert report["counts"] == {"elements": 1, "tags": 1, "values": 0}
    assert len(report["warnings"]) == 2 and not report["blocking"]
    text = checks.content_text(report)
    assert text.count("WARN: ") == 2


# --- change list ----------------------------------------------------------


def dry_run(modified, by_category=None, failures=None, decision="rolled_back"):
    return {"response": {"mode": "dry_run", "status": "ok", "decision": decision,
                         "failures": failures or [],
                         "changes": {"modified": modified, "modified_count": len(modified),
                                     "by_category": by_category or {}}}}


def test_unexpected_category_is_a_stop_not_regeneration():
    preview = {"edited_categories": ["Floors"], "expected_dependent_categories": []}
    run = dry_run([{"id": 1, "category": "Floors"}, {"id": 2, "category": "Keynote Tags"}],
                  {"Floors": 1, "Keynote Tags": 1})
    review = checks.review_change_list(run, preview)
    assert review["blocking"]
    assert review["unexpected"] == ["Keynote Tags"]
    assert any("Unexpected category: Keynote Tags" in s for s in review["stops"])
    assert any("no before/after text" in s for s in review["stops"])


def test_named_annotations_with_text_pass_and_show_changes():
    preview = {"edited_categories": ["Floors"], "expected_dependent_categories": ["Keynote Tags"]}
    run = dry_run([{"id": 1, "category": "Floors"}, {"id": 2, "category": "Keynote Tags"},
                   {"id": 3, "category": "Keynote Tags"}],
                  {"Floors": 1, "Keynote Tags": 2})
    notes = [{"id": 2, "category": "Keynote Tags", "before": "F-01", "after": "F-01"},
             {"id": 3, "category": "Keynote Tags", "before": "F-01", "after": ""}]
    review = checks.review_change_list(run, preview, notes)
    assert not review["blocking"]
    assert [r["id"] for r in review["text_changes"]] == [3]
    text = checks.change_list_text(review)
    assert "EMPTY AFTER" in text and "'F-01' -> 'F-01'" in text


def test_uncategorized_elements_are_a_stop():
    preview = {"edited_categories": ["Walls"]}
    run = dry_run([{"id": 1, "category": "Walls"}], {"Walls": 1, "(no category)": 13})
    review = checks.review_change_list(run, preview)
    assert any("13 uncategorized" in s for s in review["stops"])


def test_annotation_counts_without_ids_are_a_stop():
    preview = {"edited_categories": ["Floors"], "expected_dependent_categories": ["Keynote Tags"]}
    run = dry_run([101, 102], {"Floors": 1, "Keynote Tags": 1})
    review = checks.review_change_list(run, preview)
    assert any("no element ids" in s for s in review["stops"])


def test_nested_by_category_is_summed():
    run = {"changes": {"by_category": {"added": {"Tags": 2}, "modified": {"Tags": 1, "Walls": 3}}}}
    assert checks._by_category(run["changes"]) == {"Tags": 3, "Walls": 3}


def test_annotation_rows_join_before_and_after():
    before = {"columns": ["ElementId", "Category", "Text"],
              "rows": [[2, "Keynote Tags", "F-01"], [3, "Keynote Tags", "F-02"]]}
    after = [{"id": 3, "category": "Keynote Tags", "text": "F-03"}]
    rows = checks.annotation_rows(before, after)
    assert rows == [{"id": "2", "category": "Keynote Tags", "before": "F-01", "after": None},
                    {"id": "3", "category": "Keynote Tags", "before": "F-02", "after": "F-03"}]


# --- failures (#255) ------------------------------------------------------


def test_error_in_failures_of_a_committed_run_is_found():
    run = {"status": "ok", "decision": "committed", "failures": [
        {"severity": "Warning", "description": "Highlighted walls overlap."},
        {"severity": "Error", "description": "You now own the element, but your file is out of "
                                             "date. You must Reload Latest before editing."}]}
    errors = checks.failure_errors(run)
    assert len(errors) == 1 and "Reload Latest" in errors[0]["text"]
    text = checks.failures_text(run)
    assert text.startswith("STOP: the run (decision: committed) has 1 Error-severity")


def test_warnings_only_are_not_errors():
    assert checks.failure_errors({"failures": [{"severity": "warning", "description": "x"}]}) == []
    assert checks.failures_text({"failures": []}) == "No Error in failures."


def test_error_in_failures_also_blocks_the_change_list():
    run = dry_run([], failures=[{"severity": "Error", "description": "boom"}])
    review = checks.review_change_list(run, {})
    assert review["blocking"] and review["errors"][0]["text"] == "boom"


# --- CLI ------------------------------------------------------------------


def write(tmp, name, data):
    path = os.path.join(tmp, name)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data))
    return path


def run_cli(args):
    import importlib.util
    spec = importlib.util.spec_from_file_location("dry_run_checks_cli", CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main(args)


def test_cli_content_failures_and_change_list(capsys):
    tmp = tempfile.mkdtemp()
    content = {"regenerated": True, "view": plan_view(),
               "elements": [element(2, (0, 0, 28), (1, 1, 32))], "tags": [], "values": []}
    dry = write(tmp, "dry.json", {"response": {"result": {"rows": [], "content": content}}})
    assert run_cli(["content", "--dryrun", dry]) == 1
    assert "above the view range" in capsys.readouterr().out
    clean = write(tmp, "clean.json", {"result": {"content": {"regenerated": True, "elements": []}}})
    assert run_cli(["content", "--dryrun", clean]) == 0
    committed = write(tmp, "run.json", {"decision": "committed",
                                        "failures": [{"severity": "Error", "description": "x"}]})
    assert run_cli(["failures", "--run", committed]) == 1
    preview = write(tmp, "p.json", {"edited_categories": ["Walls"]})
    ok = write(tmp, "ok.json", dry_run([{"id": 1, "category": "Walls"}], {"Walls": 1}))
    assert run_cli(["change-list", "--preview", preview, "--dryrun", ok]) == 0
    before = write(tmp, "before.json", {"result": {"columns": ["ElementId", "Text"],
                                                   "rows": [[5, "A"]]}})
    after = write(tmp, "after.json", {"result": {"content": {"tags": [{"id": 5, "text": "B"}]}}})
    out = os.path.join(tmp, "notes.json")
    assert run_cli(["annotation-text", "--before", before, "--after", after, "--out", out]) == 0
    with io.open(out, encoding="utf-8") as f:
        assert json.load(f)["annotations"][0]["after"] == "B"
    bad = write(tmp, "bad.json", {"result": {"rows": []}})
    assert run_cli(["content", "--dryrun", bad]) == 2



# --- dry_run_content.py with a fake Revit ---------------------------------


class _XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = float(x), float(y), float(z)


class _Id(object):
    def __init__(self, value):
        self.Value = int(value)

    def __eq__(self, other):
        return isinstance(other, _Id) and other.Value == self.Value

    def __hash__(self):
        return self.Value


class _Box(object):
    def __init__(self, lo, hi):
        self.Min, self.Max = _XYZ(*lo), _XYZ(*hi)
        self.Transform = None


class _Level(object):
    def __init__(self, eid, elevation):
        self.Id, self.ProjectElevation = _Id(eid), elevation


class _ViewPlan(object):
    def __init__(self):
        self.Id, self.Name, self.CropBoxActive, self.GenLevel = _Id(20), "Plan", False, None

    def GetViewRange(self):
        return _Range()


class _Range(object):
    def GetLevelId(self, plane):
        return _Id(5)

    def GetOffset(self, plane):
        return {"depth": -1.0, "top": 7.5}[plane]


class _Tag(object):
    def __init__(self, eid, text, host, end):
        self.Id, self.TagText, self.HasLeader = _Id(eid), text, True
        self.Category = type("C", (), {"Name": "Keynote Tags"})()
        self.LeaderEndCondition, self._host, self._end = "free", host, end

    def GetTaggedLocalElementIds(self):
        return [_Id(self._host)]

    def GetTaggedReferences(self):
        return ["ref"]

    def GetLeaderEnd(self, ref):
        return _XYZ(*self._end)


class _Equipment(object):
    def __init__(self, eid, lo, hi):
        self.Id, self.Name, self._box = _Id(eid), "<family>", _Box(lo, hi)
        self.Category = type("C", (), {"Name": "Specialty Equipment"})()

    def get_BoundingBox(self, view):
        return self._box

    def IsHidden(self, view):
        return False

    def LookupParameter(self, name):
        return type("P", (), {"HasValue": True, "StorageType": "double",
                              "AsDouble": lambda self: 42.0})()


def test_dry_run_content_collect_feeds_the_checks(monkeypatch):
    import importlib
    from types import SimpleNamespace as NS
    db = NS(XYZ=_XYZ, ElementId=_Id, ViewPlan=_ViewPlan, View=_ViewPlan, Level=_Level,
            TextNote=type("TextNote", (), {}), IndependentTag=_Tag,
            PlanViewPlane=NS(ViewDepthPlane="depth", TopClipPlane="top"),
            PlanViewRange=NS(Current=_Id(-2), Unlimited=_Id(-3), LevelBelow=_Id(-4), LevelAbove=_Id(-5)),
            LeaderEndCondition=NS(Free="free"), StorageType=NS(Double="double", Integer="int",
                                                                 ElementId="id"))
    db.ElementId.InvalidElementId = _Id(-1)
    monkeypatch.setitem(sys.modules, "System", NS(Int64=int))
    monkeypatch.setitem(sys.modules, "pyrevit", NS(api=NS(DB=db)))
    monkeypatch.setitem(sys.modules, "pyrevit.api", NS(DB=db))
    monkeypatch.syspath_prepend(os.path.join(HERE, "..", "scripts"))
    sys.modules.pop("dry_run_content", None)
    content_mod = importlib.import_module("dry_run_content")
    elements = {20: _ViewPlan(), 5: _Level(5, 10.0),
                30: _Equipment(30, (0, 0, 40), (1, 1, 44)),
                31: _Equipment(31, (0, 0, 10), (1, 1, 12)),
                40: _Tag(40, "", 31, (60, 0, 0))}
    regenerated = []
    doc = NS(GetElement=lambda i: elements.get(i.Value), Regenerate=lambda: regenerated.append(1))
    content = content_mod.collect(doc, 20, [30, 31, 40], value_reads=[(31, "Area")])
    assert regenerated == [1]
    assert content["view"]["view_range"] == {"bottom": 9.0, "top": 17.5}
    assert [e["id"] for e in content["elements"]] == [30, 31]
    assert content["tags"][0]["leader_ends"] == [[60.0, 0.0, 0.0]]
    assert content["values"] == [{"id": 31, "name": "Area", "value": 42.0}]
    report = checks.content_report(content)
    texts = [w["text"] for w in report["warnings"]]
    assert any("Specialty Equipment 30 is above the view range" in t for t in texts)
    assert any("Keynote Tags 40 has empty text" in t for t in texts)
    assert any("the leader ends 59.00 ft from its host" in t for t in texts)
    sys.modules.pop("dry_run_content", None)

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))

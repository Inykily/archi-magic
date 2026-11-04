# -*- coding: utf-8 -*-
"""Tests for the color fill scheme pure functions in scripts/model_health.py (issue #78).

The script runs inside Revit, but its imports are guarded, so plain CPython can load it
and use the pure functions. All data here is invented. The Revit reader itself
(read_color_schemes) needs a live model and is not tested here.

Run:
    python -m pytest -q skills/am-model-health/tests
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "model_health.py")


def load():
    spec = importlib.util.spec_from_file_location("model_health", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mh = load()


def scheme(sid, name, area, title="", entries=3):
    return mh.color_scheme_row(sid, name, "Areas", area, entries, title)


def view(vid, name, template="", sheet=""):
    return {"id": vid, "name": name, "template": template, "sheet": sheet}


def test_acceptance_two_area_schemes_used_and_unused():
    """Issue acceptance: 2 area schemes, each with one used and one unused scheme
    of the same name -> 4 rows, 2 marked unused, area scheme shown for each."""
    rows = [scheme(1, "Scheme", "North"), scheme(2, "Scheme", "North"),
            scheme(3, "Scheme", "South"), scheme(4, "Scheme", "South")]
    mh.attach_color_use(rows[0], "view", view(11, "Level 1"))
    mh.attach_color_use(rows[2], "view", view(12, "Level 1"))
    mh.finalize_color_schemes(rows)
    assert len(rows) == 4
    unused = [r for r in rows if "unused" in r["flags"]]
    assert sorted([r["id"] for r in unused]) == [2, 4]
    assert rows[0]["area_scheme"] in ("North", "South")
    assert set([r["area_scheme"] for r in rows]) == set(["North", "South"])
    assert set([r["name"] for r in rows]) == set(["Scheme"])


def test_template_trap_view_keeps_its_own_scheme():
    """A view under a template whose scheme belongs to another area scheme is
    reported with the scheme the view really uses, not the template's."""
    template_scheme = scheme(1, "Scheme", "North")
    view_scheme = scheme(2, "Scheme", "South")
    mh.attach_color_use(template_scheme, "template", {"id": 21, "name": "Working"})
    mh.attach_color_use(view_scheme, "view", view(22, "Level 1", template="Working"))
    mh.finalize_color_schemes([template_scheme, view_scheme])
    assert template_scheme["views_count"] == 0
    assert template_scheme["templates_count"] == 1
    assert "used by templates only" in template_scheme["flags"]
    assert view_scheme["views_count"] == 1
    assert view_scheme["views"][0]["template"] == "Working"
    assert "used by templates only" not in view_scheme["flags"]


def test_same_name_across_area_schemes_flagged():
    rows = [scheme(1, "Scheme", "North"), scheme(2, "Scheme", "South")]
    mh.attach_color_use(rows[0], "view", view(11, "Level 1"))
    mh.attach_color_use(rows[1], "view", view(12, "Level 1"))
    mh.finalize_color_schemes(rows)
    assert "same name on several area schemes" in rows[0]["flags"]
    assert "same name on several area schemes" in rows[1]["flags"]


def test_same_name_one_area_scheme_not_flagged():
    rows = [scheme(1, "Scheme", "North"), scheme(2, "Other", "North")]
    mh.attach_color_use(rows[0], "view", view(11, "Level 1"))
    mh.attach_color_use(rows[1], "view", view(12, "Level 1"))
    mh.finalize_color_schemes(rows)
    assert "same name on several area schemes" not in rows[0]["flags"]
    assert "same name on several area schemes" not in rows[1]["flags"]


def test_default_legend_title_flagged():
    used = scheme(1, "Scheme", "North", title="Schema 1 Legend")
    renamed = scheme(2, "Scheme", "North", title="Scheme Legend")
    mh.attach_color_use(used, "view", view(11, "Level 1"))
    mh.attach_color_use(renamed, "view", view(12, "Level 1"))
    mh.finalize_color_schemes([used, renamed])
    assert "default legend title" in used["flags"]
    assert "default legend title" not in renamed["flags"]


def test_legend_use_keeps_scheme_used():
    row = scheme(1, "Scheme", "North")
    mh.attach_color_use(row, "legend", {"id": 31, "name": "Scheme Legend", "owner_view": "Level 1"})
    mh.finalize_color_schemes([row])
    assert "unused" not in row["flags"]
    assert row["legends_count"] == 1
    assert row["legends"][0]["owner_view"] == "Level 1"


def test_sort_unused_first_then_name():
    used = scheme(1, "Zulu", "North")
    unused = scheme(2, "Alpha", "North")
    mh.attach_color_use(used, "view", view(11, "Level 1"))
    rows = [used, unused]
    mh.finalize_color_schemes(rows)
    assert rows[0]["id"] == 2  # unused first, even though its name sorts later


def test_label_and_details_flagged_only():
    used = scheme(1, "Scheme", "North", title="Scheme Legend", entries=5)
    unused = scheme(2, "Spare", "North", title="", entries=2)
    mh.attach_color_use(used, "view", view(11, "Level 1", template="Working", sheet="A101"))
    mh.finalize_color_schemes([used, unused])
    label = mh.color_scheme_label(used)
    assert label.startswith("Scheme (Areas, North): 1 view(s), 0 template(s), 0 legend(s), 5 entries")
    assert "legend title Scheme Legend" in label
    details = mh.color_scheme_details([used, unused])
    assert [d["ids"] for d in details] == [[2]]  # only the flagged (unused) scheme
    assert details[0]["count"] == 1


def test_label_without_entry_count_or_title():
    row = scheme(1, "Scheme", "North", title="", entries=None)
    mh.attach_color_use(row, "view", view(11, "Level 1"))
    label = mh.color_scheme_label(row)
    assert "entries" not in label
    assert "legend title" not in label
    assert "no area scheme" not in label


def test_label_no_area_scheme_for_rooms():
    row = mh.color_scheme_row(1, "Scheme", "Rooms", "", 4, "")
    mh.attach_color_use(row, "view", view(11, "Level 1"))
    assert "Rooms, no area scheme" in mh.color_scheme_label(row)


def test_view_list_capped_but_count_exact():
    old = mh.MAX_ROWS
    mh.MAX_ROWS = 3
    try:
        row = scheme(1, "Scheme", "North")
        for i in range(5):
            mh.attach_color_use(row, "view", view(10 + i, "View %d" % i))
        assert row["views_count"] == 5
        assert len(row["views"]) == 3
    finally:
        mh.MAX_ROWS = old


def test_summary_counts():
    rows = [scheme(1, "Scheme", "North", title="Schema 1 Legend"),
            scheme(2, "Scheme", "South"),
            scheme(3, "Other", "North")]
    mh.attach_color_use(rows[0], "view", view(11, "Level 1"))
    mh.attach_color_use(rows[0], "template", {"id": 21, "name": "Working"})
    mh.attach_color_use(rows[2], "template", {"id": 22, "name": "Working"})
    mh.finalize_color_schemes(rows)
    s = mh.summarize_color_schemes(rows)
    assert s == {"schemes": 3, "unused": 1, "same_name": 2,
                 "default_titles": 1, "template_only": 1}

# -*- coding: utf-8 -*-
"""Tests for scripts/lib/naming_rules.py and scripts/naming_tables.py.

Run either way:
    python -m pytest skills/am-naming-standards/tests -q
    python skills/am-naming-standards/tests/test_naming_rules.py

Every test pins a rule from archi-magic issue #93, including its
four acceptance ideas: a filter that uses a type name shows in
the preview, a line style rename uses the subcategory element,
a delete used by a hidden member of an unplaced group type is
flagged before the dry run, and a "no ( )" rule reports
data-derived "( )" names before the rename is called done.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import naming_rules as nr  # noqa: E402
import naming_tables as nt  # noqa: E402


def rules(**over):
    r = nr.default_rules()
    r.update(over)
    return r


def row(i, name, category="text_type", **over):
    r = {"id": i, "category": category, "name": name,
         "instance_count": 0, "referencing_type_count": None,
         "sketch_dimension_count": 0, "in_reference_view_only": False,
         "real_size": ""}
    r.update(over)
    return r


# --- Scale tokens (issue point 2) ---

def test_scale_engineering():
    assert nr.parse_scale_token("1-30") == ("engineering", "1-30", None)


def test_scale_architectural():
    assert nr.parse_scale_token("1-32in") == ("architectural", "1-32in", None)


def test_scale_old_form_rejected():
    style, _norm, err = nr.parse_scale_token("1in=30ft")
    assert style is None
    assert "1-30" in err


# --- Case, acronyms, separators (issue point 1) ---

def test_pascal_case_with_separators():
    new, flags = nr.transform_name("all caps purpose_scale", rules())
    assert new == "All_Caps_Purpose_Scale"
    assert flags == []


def test_known_acronyms_stay_capitals():
    new, _flags = nr.transform_name("solid trn fill opq", rules())
    assert new == "Solid_TRN_Fill_OPQ"


def test_unknown_all_caps_word_is_flagged_not_guessed():
    new, flags = nr.transform_name("dept XYZ hatch", rules())
    assert "unknown_acronym" in flags
    assert new == "Dept_Xyz_Hatch"


def test_user_acronym_list_extends_defaults():
    new, flags = nr.transform_name("mech HVAC tag", rules(acronyms=["TRN", "OPQ", "HVAC"]))
    assert new == "Mech_HVAC_Tag"
    assert flags == []


def test_brackets_rejected():
    assert "has_brackets" in nr.validate_name("Type [A]", rules())


def test_double_space_and_double_separator_flagged():
    flags = nr.validate_name("Type  Name__X", rules())
    assert "double_space" in flags
    assert "double_separator" in flags


# --- Data-derived parts (issue point 3) ---

def test_data_part_kept_exact():
    new, flags = nr.transform_name(
        "program dept (a) solid", rules(), keep_exact=["dept (a)"])
    assert new == "Program_dept (a)_Solid"
    assert "data_part_kept" in flags


def test_no_parens_rule_reports_data_part_parens_before_done():
    table = nr.build_rename_table(
        [row(1, "program dept (a) solid", "filled_region_type",
             keep_exact=["dept (a)"])],
        rules(allow_parens=False))
    assert "data_part_has_parens" in table[0]["flags"]


def test_parens_allowed_clears_the_blocker():
    table = nr.build_rename_table(
        [row(1, "program dept (a) solid", "filled_region_type",
             keep_exact=["dept (a)"])],
        rules(allow_parens=True))
    assert "data_part_has_parens" not in table[0]["flags"]


# --- Size in the name (issue point 5) ---

def test_size_mismatch_flagged():
    assert nr.size_mismatch("Text 3mm", "2.5mm") is True
    assert nr.size_mismatch("Text 3mm", "3mm") is False
    assert nr.size_mismatch("Text note", "3mm") is False


# --- Usage counts (issue point 5) ---

def test_sketch_dimensions_excluded_from_count():
    _count, note = nr.usage_for_display(
        row(1, "Dim style", "dimension_type",
            instance_count=229000, sketch_dimension_count=229000))
    assert _count == 0
    assert note == "sketch dimensions excluded"


def test_reference_view_only_noted():
    _count, note = nr.usage_for_display(
        row(1, "Fill", "filled_region_type",
            instance_count=4, in_reference_view_only=True))
    assert note == "used only in the reference view"


def test_referencing_type_count_wins_over_instances():
    count, _note = nr.usage_for_display(
        row(1, "Head", "text_type",
            instance_count=0, referencing_type_count=3))
    assert count == 3


# --- Line style rename path (issue point 4) ---

def test_line_style_uses_subcategory_element():
    table = nr.build_rename_table(
        [row(7, "thin lines", "line_style")], rules())
    assert "doc.GetElement(subcategory.Id).Name" in table[0]["name_path"]
    assert table[0]["new"] == "Thin_Lines"


# --- Filter scan (issue point 7, acceptance idea 1) ---

def test_filter_using_old_name_lists_in_preview():
    filters = [{"id": 9, "name": "Walls by fill",
                "values": ["Filled region type equals Old Fill"]}]
    hits = nr.scan_filter_refs(filters, ["Old Fill"])
    assert len(hits) == 1
    assert hits[0]["filter_name"] == "Walls by fill"
    assert hits[0]["old_name"] == "Old Fill"


def test_filter_scan_covers_schedule_filters():
    filters = [{"id": 10, "name": "Door schedule", "kind": "schedule_filter",
                "values": ["Type Mark equals Old Door"]}]
    hits = nr.scan_filter_refs(filters, ["Old Door"])
    assert hits[0]["filter_kind"] == "schedule_filter"


def test_filter_scan_misses_unrelated_names():
    filters = [{"id": 9, "name": "Walls by fill",
                "values": ["Filled region type equals New Fill"]}]
    assert nr.scan_filter_refs(filters, ["Old Fill"]) == []


# --- Delete checks (issue point 6, acceptance idea 3) ---

def test_hidden_member_of_unplaced_group_flags_delete():
    flags = nr.check_delete(
        row(5, "Old Fill", "filled_region_type"),
        [{"id": 50, "name": "Detail group A"}], {})
    assert "unplaced_groups_exist" in flags


def test_known_group_member_flagged():
    flags = nr.check_delete(
        row(5, "Old Fill", "filled_region_type"),
        [], {50: [5, 6]})
    assert "used_by_group_member" in flags


def test_dry_run_list_compared_with_expected():
    unexpected, missing = nr.compare_dry_run([1, 2], [2, 3])
    assert unexpected == [3]
    assert missing == [1]


# --- Reference-view label plan (issue point 8) ---

def test_label_plan_updates_renamed_labels():
    views = [{"id": 20, "name": "Line style samples", "kind": "reference",
              "labels": [{"text": "Thin Lines", "sample_style_exists": True,
                          "starts_with_type_name": True,
                          "has_labels": True}]}]
    plan = nr.plan_reference_labels(views, {"Thin Lines": "Thin_Lines"})
    assert plan[0]["action"] == "update_text"
    assert plan[0]["new_label"] == "Thin_Lines"


def test_label_plan_flags_missing_sample_style():
    views = [{"id": 20, "name": "Line style samples", "kind": "reference",
              "labels": [{"text": "Ghost Style", "sample_style_exists": False,
                          "starts_with_type_name": False,
                          "has_labels": True}]}]
    plan = nr.plan_reference_labels(views, {})
    assert plan[0]["action"] == "check_sample"


def test_label_plan_marks_dimension_groups_without_labels():
    views = [{"id": 21, "name": "Dim samples", "kind": "reference",
              "labels": [{"text": "", "sample_style_exists": True,
                          "starts_with_type_name": False,
                          "has_labels": False}]}]
    plan = nr.plan_reference_labels(views, {})
    assert plan[0]["action"] == "no_labels"


# --- End-to-end tables step ---

def test_tables_step_reports_paren_blockers():
    inventory = {
        "rows": [row(1, "program dept (a) solid", "filled_region_type",
                     keep_exact=["dept (a)"])],
        "view_filters": [{"id": 9, "name": "F",
                          "values": ["type equals program dept (a) solid"]}],
        "schedule_filters": [],
        "unplaced_group_types": [],
        "placed_group_members": {},
        "reference_views": [],
        "not_checked": []}
    tables = nt.build_tables(inventory, rules(allow_parens=False))
    assert len(tables["paren_blockers"]) == 1
    assert len(tables["filter_refs"]) == 1
    assert tables["not_checked"] == []

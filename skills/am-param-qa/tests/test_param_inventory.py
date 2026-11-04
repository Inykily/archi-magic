# -*- coding: utf-8 -*-
"""Tests for the inventory pure functions in scripts/param_inventory.py (issue #100).

The script runs inside Revit, but its imports are guarded, so plain CPython can load it
and use the pure functions. All data here is invented: no project, client, or building
names, no element ids from a real model.

Run:
    python3 -m pytest -q skills/am-param-qa/tests
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "param_inventory.py")


def load():
    spec = importlib.util.spec_from_file_location("param_inventory", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pi = load()


def test_loads_outside_revit_without_running_the_check():
    assert pi.DB is None
    assert pi.DOC is None
    assert pi.result["error"] == "no_project_document"


def test_name_rule_forbid_chars():
    assert pi.name_rule_violations("Fire Rating", {"forbid_chars": " -"}) == [
        "contains space"]
    assert pi.name_rule_violations("Fire-Rating", {"forbid_chars": " -"}) == [
        "contains '-'"]
    assert pi.name_rule_violations("FireRating", {"forbid_chars": " -"}) == []
    assert pi.name_rule_violations("Mark", {"forbid_chars": " -"}) == []


def test_name_rule_case():
    assert pi.name_rule_violations("fireRating", {"case": "Pascal"}) == ["not PascalCase"]
    assert pi.name_rule_violations("FireRating", {"case": "Pascal"}) == []
    assert pi.name_rule_violations("Fire_Rating", {"case": "Pascal"}) == ["not PascalCase"]
    assert pi.name_rule_violations("fireRating", {"case": "camel"}) == []
    assert pi.name_rule_violations("FireRating", {"case": "camel"}) == ["not camelCase"]
    assert pi.name_rule_violations("MARK", {"case": "lower"}) == ["not lower case"]
    assert pi.name_rule_violations("mark", {"case": "lower"}) == []
    assert pi.name_rule_violations("Mark", {"case": "upper"}) == ["not upper case"]
    assert pi.name_rule_violations("Mark", {}) == []
    assert pi.name_rule_violations("Mark", None) == []


def test_join_usage_guid_wins_over_name():
    by_guid = {"g1": {"schedule_fields": 31, "schedule_filters": 2, "view_filters": 1}}
    by_name = {"Mark": {"schedule_fields": 5, "schedule_filters": 0, "view_filters": 0}}
    usage, match = pi.join_usage("g1", "Mark", by_guid, by_name)
    assert usage["schedule_fields"] == 31
    assert match == "guid"
    usage, match = pi.join_usage("g9", "Mark", by_guid, by_name)
    assert usage["schedule_fields"] == 5
    assert match == "name"
    usage, match = pi.join_usage("", "Nope", by_guid, by_name)
    assert usage == {"schedule_fields": 0, "schedule_filters": 0, "view_filters": 0}
    assert match == "none"


def test_compute_flags_duplicate_and_unbound():
    name_keys = {"Mark": {"g1", "g2"}, "Dept": {"g3"}}
    row = {"name": "Mark", "binding": "instance", "group_other": False,
           "usage_match": "name"}
    assert pi.compute_flags(row, name_keys, None) == ["duplicate-name", "usage-ambiguous"]
    row = {"name": "Dept", "binding": "unbound", "group_other": True,
           "usage_match": "guid"}
    assert pi.compute_flags(row, name_keys, None) == ["unbound", "group-other"]
    row = {"name": "Dept", "binding": "instance", "group_other": False,
           "usage_match": "guid"}
    assert pi.compute_flags(row, name_keys, {"forbid_chars": " "}) == []


def test_compute_flags_name_rule():
    name_keys = {"Fire Rating": {"g1"}}
    row = {"name": "Fire Rating", "binding": "type", "group_other": False,
           "usage_match": "guid"}
    flags = pi.compute_flags(row, name_keys, {"forbid_chars": " ", "case": "Pascal"})
    assert flags == ["name-rule: contains space", "name-rule: not PascalCase"]


def test_csv_escape_and_rows():
    assert pi.csv_escape("plain") == "plain"
    assert pi.csv_escape("a,b") == '"a,b"'
    assert pi.csv_escape('say "hi"') == '"say ""hi"""'
    row = {"name": "Mark, Dept", "kind": "shared", "guid": "g1", "data_type": "Text",
           "group": "Identity Data", "binding": "instance", "categories": ["Doors"],
           "fill_rate": 80.0, "filled": 8, "total": 10,
           "usage": {"schedule_fields": 31, "schedule_filters": 2, "view_filters": 1},
           "families": ["Title Block"], "flags": ["duplicate-name"]}
    csv = pi.inventory_csv([row])
    lines = csv.split("\n")
    assert lines[0].startswith("name,kind,guid")
    assert '"Mark, Dept",shared,g1,Text,Identity Data,instance,Doors,80.0,8,10,31,2,1,Title Block,duplicate-name' == lines[1]


def test_csv_missing_fill_rate_is_blank():
    row = {"name": "Dept", "kind": "project", "guid": "", "data_type": "Text",
           "group": "Other", "binding": "unbound", "categories": [],
           "fill_rate": None, "filled": None, "total": None,
           "usage": {"schedule_fields": 0, "schedule_filters": 0, "view_filters": 0},
           "families": [], "flags": ["unbound"]}
    line = pi.inventory_csv([row]).split("\n")[1]
    assert line == "Dept,project,,Text,Other,unbound,,,,,0,0,0,,unbound"


def test_summarize():
    rows = [
        {"name": "A", "binding": "instance", "flags": []},
        {"name": "B", "binding": "type", "flags": ["duplicate-name"]},
        {"name": "C", "binding": "unbound", "flags": ["unbound", "group-other"]},
        {"name": "D", "binding": "unbound",
         "flags": ["unbound", "name-rule: contains space"]},
    ]
    s = pi.summarize(rows)
    assert s == {"parameters": 4, "bound": 2, "unbound_shared": 2,
                 "duplicate_names": 1, "group_other": 1, "name_rule_violations": 1}

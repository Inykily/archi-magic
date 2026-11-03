# -*- coding: utf-8 -*-
"""Tests for scripts/lib/ownership.py and scripts/ownership.py (issue #97).

Run either way:
    python -m pytest skills/am-safe-change/tests -q
    python skills/am-safe-change/tests/test_ownership.py
"""
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
FIXTURES = os.path.join(HERE, "..", "assets", "fixtures")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))

import ownership as ow  # noqa: E402  (lib/ownership.py; the CLI of the same name loads by path)


def fixture(name):
    with io.open(os.path.join(FIXTURES, name), "r", encoding="utf-8-sig") as f:
        return json.load(f)


def el(i, status="NotOwned", owner="", updates="CurrentWithCentral", cat="Views", name="V"):
    return {"id": i, "exists": True, "status": status, "owner": owner,
            "updates": updates, "category": cat, "name": name}


def read(elements, scan_borrowed=None, partial=False, workshared=True):
    return {"workshared": workshared, "user": "me", "elements": elements,
            "scan": {"categories": ["Views"], "checked": 10, "partial": partial},
            "scan_borrowed": scan_borrowed or []}


# --- target ids -----------------------------------------------------------

def test_target_ids_sheet_shift_list_steps():
    p = fixture("snowdon-sheet-shift.preview.json")
    ids = ow.target_ids(p)
    assert ids == [st[0] for st in p["steps"]]


def test_target_ids_transforms_dict_steps():
    p = fixture("snowdon-element-transforms.preview.json")
    assert ow.target_ids(p) == [st["id"] for st in p["steps"]]


def test_target_ids_detail_views_use_sheet_not_source_or_type():
    p = {"steps": [{"name": "D1", "sheet_id": 7, "source_view_id": 11, "viewport_type_id": 12},
                   {"name": "D2", "sheet_id": 7, "source_view_id": 13, "viewport_type_id": 12}]}
    assert ow.target_ids(p) == [7]


def test_target_ids_override_and_extra_dedupe():
    p = {"ownership_ids": [5, 6, 5], "steps": [[1, "a", "b"]]}
    assert ow.target_ids(p, [6, 9]) == [5, 6, 9]


# --- pre-check ------------------------------------------------------------

def test_check_none_owned_by_others():
    s = ow.check(read([el(1), el(2, "OwnedByCurrentUser")]))
    assert s["blocked"] is False
    assert s["line"] == "0 of 2 elements owned by others."
    assert (s["mine"], s["not_owned"]) == (1, 1)


def test_check_owned_by_other_blocks_and_names_owner():
    s = ow.check(read([el(1), el(2, "OwnedByOtherUser", "asmith"),
                       el(3, "OwnedByOtherUser", "asmith"), el(4, "OwnedByOtherUser", "bjones")]))
    assert s["blocked"] is True
    assert s["line"] == "3 of 4 elements owned by others. Owners: asmith (2), bjones (1)."
    assert [o["id"] for o in s["others"]] == [2, 3, 4]
    assert "asmith" in ow.text_table(s)


def test_check_updated_in_central_blocks():
    s = ow.check(read([el(1, updates="UpdatedInCentral")]))
    assert s["blocked"] is True
    assert s["updated"] == [1]
    assert s["line"] == "0 of 1 elements owned by others."


def test_check_missing_not_counted():
    s = ow.check(read([el(1), {"id": 2, "exists": False}]))
    assert s["missing"] == [2]
    assert s["total"] == 1


def test_check_not_workshared():
    s = ow.check({"result": read([], workshared=False)})
    assert s["workshared"] is False
    assert s["blocked"] is False
    assert "not workshared" in s["line"]


def test_annotate_adds_blocking_warning_and_is_idempotent():
    p = fixture("snowdon-sheet-shift.preview.json")
    tid = p["steps"][0][0]
    s = ow.check(read([el(tid, "OwnedByOtherUser", "asmith", cat="Sheets")]))
    once = ow.annotate(p, s)
    twice = ow.annotate(once, s)
    assert twice == once
    assert once["blocked"] is True
    own_w = [w for w in once["warnings"] if w.get("source") == "ownership"]
    assert len(own_w) == 1 and own_w[0]["row"] == str(tid) and own_w[0]["blocking"] is True
    assert once["notes"][-1].startswith("Ownership: 1 of 1 elements owned by others.")
    # the original preview is not changed, and its own rows stay as they were
    assert p.get("ownership") is None
    assert once["before"] == p["before"] and once["after"] == p["after"]


def test_annotate_clean_keeps_blocked_false():
    p = {"steps": [], "notes": ["7 of 55 sheets change."], "warnings": []}
    out = ow.annotate(p, ow.check(read([el(1)])))
    assert out["blocked"] is False
    assert out["notes"] == ["7 of 55 sheets change.", "Ownership: 0 of 1 elements owned by others."]


# --- post-run report ------------------------------------------------------

def test_borrowed_counts_targets_and_scanned_dependents_once():
    r = read([el(1, "OwnedByCurrentUser", cat="Sheets"), el(2)],
             scan_borrowed=[{"id": 1, "category": "Sheets"}, {"id": 10, "category": "Views"},
                            {"id": 11, "category": "Views"}])
    b = ow.borrowed(r)
    assert b["count"] == 3
    assert b["by_category"] == [("Views", 2), ("Sheets", 1)]
    assert b["line"].startswith("You now borrow 3 elements: Views 2, Sheets 1.")
    assert "Borrowed Elements" in b["line"]


def test_borrowed_partial_scan_says_so():
    b = ow.borrowed(read([], scan_borrowed=[{"id": 10, "category": "Views"}], partial=True))
    assert b["partial"] is True
    assert "element limit" in b["line"]


def test_borrowed_none():
    assert ow.borrowed(read([el(1)]))["line"] == "You borrow none of the checked elements."


# --- CLI ------------------------------------------------------------------

def _cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ownership_cli", os.path.join(SCRIPTS, "ownership.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_inputs_check_borrowed():
    cli = _cli()
    tmp = tempfile.mkdtemp()
    try:
        prev = os.path.join(tmp, "p.preview.json")
        shutil.copy(os.path.join(FIXTURES, "snowdon-sheet-shift.preview.json"), prev)
        dry = os.path.join(tmp, "dry.json")
        with io.open(dry, "w", encoding="utf-8") as f:
            f.write(json.dumps({"result": {"modified_count": 3,
                                           "modified_by_category": {"Views": 2, "Sheets": 1}}}))
        inp = os.path.join(tmp, "in.json")
        assert cli.main(["inputs", "--preview", prev, "--dryrun", dry, "--out", inp]) == 0
        data = json.load(io.open(inp, encoding="utf-8"))
        assert data["categories"] == ["Sheets", "Views"]
        tid = data["ids"][0]
        own = os.path.join(tmp, "own.json")
        with io.open(own, "w", encoding="utf-8") as f:
            f.write(json.dumps({"result": read([el(tid, "OwnedByOtherUser", "asmith")])}))
        assert cli.main(["check", "--read", own, "--preview", prev]) == 1
        assert json.load(io.open(prev, encoding="utf-8"))["blocked"] is True
        assert cli.main(["borrowed", "--read", own]) == 0
        with io.open(prev, "w", encoding="utf-8") as f:
            f.write(json.dumps({"steps": []}))
        assert cli.main(["inputs", "--preview", prev, "--out", inp]) == 2
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)

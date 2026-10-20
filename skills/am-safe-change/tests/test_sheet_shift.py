# -*- coding: utf-8 -*-
"""Tests for scripts/lib/sheet_shift.py.

Run either way:
    python -m pytest skills/am-safe-change/tests -q
    python skills/am-safe-change/tests/test_sheet_shift.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "lib"))

import sheet_shift as ss  # noqa: E402


def sh(i, number, name="S", placeholder=False):
    return {"id": i, "number": number, "name": name, "placeholder": placeholder}


def after_map(preview):
    return dict((r[0], r[1]) for r in preview["after"])


def assert_unique_after_every_step(sheets, steps):
    """Replay steps one by one; the number set must stay unique each time."""
    current = dict((s["id"], s["number"]) for s in sheets)
    for i, st in enumerate(steps):
        current[st[0]] = st[2]
        nums = [n.lower() for n in current.values()]
        assert len(nums) == len(set(nums)), "duplicate number after step %d %r: %r" % (
            i + 1, st, sorted(nums))


BASE = [sh(1, "A101"), sh(2, "A300"), sh(3, "A301"), sh(4, "A302"), sh(5, "A303"),
        sh(6, "A305"), sh(7, "B301"), sh(8, "A401")]


def test_parse():
    assert ss.parse_number("A301") == ("A", "301", "")
    assert ss.parse_number("A301a") == ("A", "301", "a")
    assert ss.parse_number("A301.1") == ("A", "301", ".1")
    assert ss.parse_number("A-010") == ("A-", "010", "")
    assert ss.parse_number("COVER") is None


def test_plain_shift_keep_gaps():
    p = ss.compute_shift(BASE, "A301")
    m = after_map(p)
    assert [m[i] for i in (1, 2, 3, 4, 5, 6, 7, 8)] == [
        "A101", "A300", "A302", "A303", "A304", "A306", "B301", "A401"]
    assert not p["blocked"]
    assert ss.preview_counts(p)["changed"] == 4


def test_plain_shift_ordering_unique_and_no_temp():
    p = ss.compute_shift(BASE, "A301")
    assert all(not st[2].startswith(ss.TMP_PREFIX) for st in p["steps"]), p["steps"]
    assert len(p["steps"]) == 4
    assert_unique_after_every_step(BASE, p["steps"])


def test_order_changes_alone_is_safe_for_upward_shift():
    sheets = [sh(i, "A%d" % (300 + i)) for i in range(1, 21)]
    changes = [(s["id"], s["number"], "A%d" % (301 + s["id"])) for s in sheets]
    ordered = [[c[0], c[1], c[2]] for c in ss.order_changes(changes)]
    assert ss.simulate(sheets, ordered) == []
    assert_unique_after_every_step(sheets, ordered)


def test_gaps_closed():
    p = ss.compute_shift(BASE, "A301", keep_gaps=False)
    m = after_map(p)
    assert [m[i] for i in (3, 4, 5, 6)] == ["A302", "A303", "A304", "A305"]
    assert_unique_after_every_step(BASE, p["steps"])


def test_gaps_closed_needing_temp_numbers_stays_unique():
    sheets = [sh(1, "A301"), sh(2, "A304"), sh(3, "A305")]
    p = ss.compute_shift(sheets, "A301", keep_gaps=False)
    m = after_map(p)
    assert (m[1], m[2], m[3]) == ("A302", "A303", "A304")
    assert_unique_after_every_step(sheets, p["steps"])


def test_suffixes_move_with_base():
    sheets = [sh(1, "A301"), sh(2, "A301a"), sh(3, "A301.1"), sh(4, "A302")]
    p = ss.compute_shift(sheets, "A301")
    m = after_map(p)
    assert (m[1], m[2], m[3], m[4]) == ("A302", "A302a", "A302.1", "A303")
    assert_unique_after_every_step(sheets, p["steps"])


def test_suffixes_excluded_stay():
    sheets = [sh(1, "A301"), sh(2, "A301a"), sh(4, "A302")]
    p = ss.compute_shift(sheets, "A301", include_suffixed=False)
    assert after_map(p)[2] == "A301a"


def test_zero_padding_kept():
    sheets = [sh(1, "A-009"), sh(2, "A-010")]
    p = ss.compute_shift(sheets, "A-009", scope="after")
    m = after_map(p)
    assert (m[1], m[2]) == ("A-010", "A-011")


def test_out_of_scope_collision_blocks():
    # A399 leaves the A3xx series and lands on A400, which is out of scope.
    sheets = [sh(1, "A398"), sh(2, "A399"), sh(3, "A400", "EXISTING")]
    p = ss.compute_shift(sheets, "A398")
    assert p["blocked"]
    assert p["steps"] == []
    texts = " ".join(w["text"] for w in p["warnings"] if w["blocking"])
    assert "A400" in texts and "EXISTING" in texts
    assert any(w["row"] == "2" for w in p["warnings"])


def test_placeholder_excluded_still_counts_for_collisions():
    sheets = [sh(1, "A301"), sh(2, "A302", "PH", placeholder=True)]
    p = ss.compute_shift(sheets, "A301", include_placeholders=False)
    assert p["blocked"]


def test_placeholder_included_moves_and_warns():
    sheets = [sh(1, "A301"), sh(2, "A302", "PH", placeholder=True)]
    p = ss.compute_shift(sheets, "A301")
    assert not p["blocked"]
    assert after_map(p)[2] == "A303"
    assert any("placeholder" in w["text"] for w in p["warnings"])


def test_case_insensitive_collision():
    sheets = [sh(1, "A301"), sh(2, "a302", "LOWER")]
    p = ss.compute_shift(sheets, "A301", scope="custom", custom_ids=[1])
    assert p["blocked"]


def test_unescape_round_trip():
    escaped = {"escaped": True, "sheets": [
        {"id": 1, "number": "K101", "name": "Caf\\u00e9 \\\\u00e9 Kitchen", "placeholder": False}]}
    s = ss.load_read_result(escaped)
    assert s[0]["name"] == u"Café \\u00e9 Kitchen"
    plain = {"result": {"escaped": False, "sheets": [
        {"id": 1, "number": "K101", "name": u"Café", "placeholder": False}]}}
    assert ss.load_read_result(plain)[0]["name"] == u"Café"


def test_temp_numbers_use_only_allowed_characters():
    sheets = [sh(1, "A301"), sh(2, "A304"), sh(3, "A305")]
    p = ss.compute_shift(sheets, "A301", keep_gaps=False)
    temps = [st[2] for st in p["steps"] if st[2].startswith(ss.TMP_PREFIX)]
    assert temps, "this case needs temporary numbers"
    for t in temps:
        assert not (set(t) & ss.PROHIBITED), t


def test_prohibited_character_blocks():
    sheets = [sh(1, "A301;x")]
    p = ss.compute_shift(sheets, "A301")
    assert p["blocked"]


def test_compare():
    p = ss.compute_shift(BASE, "A301")
    assert ss.compare(p, p["after"]) == []
    bad = [list(r) for r in p["after"]]
    bad[0][1] = "X999"
    assert len(ss.compare(p, bad)) == 1


def test_contract_shape():
    p = ss.compute_shift(BASE, "A301")
    assert p["kind"] == "change-preview"
    assert p["keyColumn"] == "ElementId"
    assert p["columns"] == ["ElementId", "Sheet Number", "Sheet Name"]
    assert p["changedColumns"] == ["Sheet Number"]
    assert len(p["before"]) == len(p["after"]) == len(BASE)
    assert [r[0] for r in p["before"]] == [r[0] for r in p["after"]]


if __name__ == "__main__":
    names = sorted(n for n in dir() if n.startswith("test_"))
    failed = 0
    for n in names:
        try:
            globals()[n]()
            print("PASS %s" % n)
        except Exception as e:  # report every failure, then exit non-zero
            failed += 1
            print("FAIL %s: %s" % (n, e))
    print("%d passed, %d failed" % (len(names) - failed, failed))
    sys.exit(1 if failed else 0)

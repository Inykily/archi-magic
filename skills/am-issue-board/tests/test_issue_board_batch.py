# -*- coding: utf-8 -*-
"""Batch, archive, replace and recheck tests for scripts/issue_board.py.

    python -m pytest -q skills/am-issue-board/tests
"""
import io
import json
import os
import sys

import pytest

from issue_board_fixtures import SAMPLE, FakeFormattedText, make_range, list_type
import issue_board as ib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import board_cli  # noqa: E402


def apply(text, plan):
    ft = FakeFormattedText(text)
    ib.apply_plan(ft, plan, make_range, list_type)
    return ft


def write_json(tmp_path, name, data):
    p = os.path.join(str(tmp_path), name)
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=True))
    return p


def note_file(tmp_path, text):
    return write_json(tmp_path, "note.json", {"note": {"text": text, "formats": []}})


def run_cli(capsys, args):
    code = board_cli.main(args)
    out = capsys.readouterr().out
    return code, (json.loads(out) if code == 0 else None)


# ---------------------------------------------------------------- batch

BATCH_OPS = [
    {"op": "status", "number": 1, "status": "DONE", "date": "2026-01-09",
     "user": "@user1", "comment": "relinked; verified."},
    {"op": "status", "number": 2, "status": "DONE", "date": "2026-01-09",
     "user": "@user1", "comment": "simplified."},
    {"op": "comment", "number": 3, "date": "2026-01-09", "user": "@user1", "comment": "seen."},
    {"op": "relate", "a": 2, "b": 4},
    {"op": "add", "issue": {"title": "New one", "todos": ["x"]}},
]


def test_batch_is_one_plan_with_one_guard():
    plan = ib.plan_batch(SAMPLE, BATCH_OPS)
    assert plan["action"].startswith("batch:")
    assert plan["expected_sha1"] == ib.text_sha1(SAMPLE)
    ft = apply(SAMPLE, plan)
    assert ft.text == plan["final_text"]
    after = ib.parse_board(ft.text)
    assert after["warnings"] == []
    assert [(i["number"], i["status"]) for i in after["issues"]] == [
        (1, "DONE"), (2, "DONE"), (3, "OPEN"), (4, "DONE"), (5, "OPEN")]
    assert after["header"]["next_number"] == 6
    assert ib.find_issue(after, 5)["todos"] == ["x"]


def test_batch_second_relate_keeps_first_link():
    plan = ib.plan_batch(SAMPLE, [{"op": "relate", "a": 2, "b": 4},
                                   {"op": "relate", "a": 2, "b": 1}])
    after = ib.parse_board(plan["final_text"])
    assert ib.find_issue(after, 2)["related"] == [1, 4]
    assert ib.find_issue(after, 4)["related"] == [2, 3]
    assert ib.find_issue(after, 1)["related"] == [2, 3]
    assert after["warnings"] == []


def test_batch_comment_after_relate_stays_before_related():
    plan = ib.plan_batch(SAMPLE, [{"op": "relate", "a": 2, "b": 4},
                                   {"op": "comment", "number": 2, "date": "2026-01-09",
                                    "user": "@user1", "comment": "noted."}])
    i2 = ib.find_issue(ib.parse_board(plan["final_text"]), 2)
    kinds = [ln["kind"] for ln in i2["lines"]]
    assert kinds[-1] == "related" and kinds[-2] == "comment"


def test_batch_add_then_target_is_an_error():
    with pytest.raises(ib.BoardError):
        ib.plan_batch(SAMPLE, [{"op": "add", "issue": {"title": "New", "todos": ["x"]}},
                               {"op": "comment", "number": 5, "date": "2026-01-09",
                                "user": "@user1", "comment": "too soon."}])


def test_batch_rejects_bad_ops():
    with pytest.raises(ib.BoardError):
        ib.plan_batch(SAMPLE, [])
    with pytest.raises(ib.BoardError):
        ib.plan_batch(SAMPLE, [{"op": "explode", "number": 1}])
    with pytest.raises(ib.BoardError):
        ib.plan_batch(SAMPLE, [{"op": "status", "number": 1, "status": "DONE",
                                "date": "2026-01-09", "user": "@user1", "comment": " "}])
    with pytest.raises(ib.BoardError):
        ib.plan_batch(SAMPLE, [{"op": "relate", "a": 2, "b": 2}])


def test_cli_batch(tmp_path, capsys):
    note = note_file(tmp_path, SAMPLE)
    ops = write_json(tmp_path, "ops.json", {"ops": BATCH_OPS})
    code, plan = run_cli(capsys, ["batch", note, ops])
    assert code == 0
    assert plan["operations"] == ["#1 -> DONE", "#2 -> DONE", "comment #3",
                                  "relate #2 #4", "add #5"]
    ft = apply(SAMPLE, plan)
    assert ft.text == plan["final_text"]


# ---------------------------------------------------------------- archive

def test_archive_done_round_trip(tmp_path):
    out = ib.plan_archive(SAMPLE, "DONE")
    assert out["archived"] == [4] and out["archive_mode"] == "create"
    assert out["board_warnings_after"] == [] and out["archive_warnings"] == []
    assert out["parent_warnings"] == []
    ft = apply(SAMPLE, out["board_plan"])
    assert ft.text == out["board_plan"]["final_text"]
    board = ib.parse_board(ft.text)
    assert [i["number"] for i in board["issues"]] == [1, 2, 3]
    # No pile of blank paragraphs where #4 was cut: no two blanks in a row.
    paras = [t for _, t in ib.split_paragraphs(ft.text)]
    assert all(not (a == "" and b == "") for a, b in zip(paras, paras[1:]))
    archive = ib.parse_board(out["archive_plan"]["final_text"])
    assert [i["number"] for i in archive["issues"]] == [4]
    assert archive["header"]["archive"] is True
    assert ib.find_issue(archive, 4)["title"] == "Survey point check"


def test_archive_middle_issue_keeps_neighbors():
    out = ib.plan_archive(SAMPLE, "IN PROGRESS")
    assert out["archived"] == [1]
    ft = apply(SAMPLE, out["board_plan"])
    assert [i["number"] for i in ib.parse_board(ft.text)["issues"]] == [2, 3, 4]
    assert ib.parse_board(ft.text)["warnings"] == []


def test_archive_keeps_formats():
    text = "\r".join([
        "AUDIT - 2026-01-05 (by @user1)",
        "Issues use fixed numbers; next new issue is #3. Never renumber.",
        "",
        "#1 [OPEN] Keep me - @user1",
        "Finding: a (id1001).",
        "",
        "#2 [DONE] Archive me - @user2",
        "Finding: b (id2001) and c (id2002):",
        "Detail row (id2003).",
        "To do: none.",
        "2026-01-06 @user1: closed.",
    ]) + "\r"
    out = ib.plan_archive(text, "DONE")
    plan = out["archive_plan"]
    ft = FakeFormattedText(plan["final_text"])
    ib.apply_formats(ft, plan["formats"], make_range, list_type)
    paras = dict((t, s) for s, t in ib.split_paragraphs(ft.text))
    title = ft.para_attr(paras["#2 [DONE] Archive me - @user2"])
    assert title["bold"] and title["list"] == "none" and title["indent"] == 0
    line = "Finding: b (id2001) and c (id2002):"
    ls = paras[line]
    for ident in ("id2001", "id2002"):
        i = line.index(ident)
        assert all(ft.attr[ls + k]["ul"] for k in range(i, i + len(ident)))
    detail = "Detail row (id2003)."
    ds = paras[detail]
    assert ft.para_attr(ds)["indent"] == 2
    i = detail.index("id2003")
    assert all(ft.attr[ds + k]["ul"] for k in range(i, i + 6))


def test_archive_append_inserts_in_number_order():
    first = ib.plan_archive(SAMPLE, "DONE")
    archive_text = first["archive_plan"]["final_text"]
    # A second board run archives #1 and #2 (both DONE in this variant,
    # #4 left OPEN so it is not archived twice).
    variant = (SAMPLE.replace("#1 [IN PROGRESS]", "#1 [DONE]")
               .replace("#2 [OPEN]", "#2 [DONE]").replace("#4 [DONE]", "#4 [OPEN]"))
    out = ib.plan_archive(variant, "DONE", archive_text=archive_text)
    assert out["archive_mode"] == "append"
    ft = apply(archive_text, out["archive_plan"])
    assert ft.text == out["archive_plan"]["final_text"]
    assert [i["number"] for i in ib.parse_board(ft.text)["issues"]] == [1, 2, 4]
    assert ib.parse_board(ft.text)["warnings"] == []


def test_archive_legacy_note_gets_marker_line():
    legacy = "\r".join([
        "ARCHIVE - AUDIT - 2026-01-05 (by @user1)",
        "",
        "#9 [DONE] Old one - @user1",
        "To do: none.",
    ]) + "\r"
    assert ib.parse_board(legacy)["warnings"]  # no next-number line, no marker: warns
    out = ib.plan_archive(SAMPLE, "DONE", archive_text=legacy)
    assert out["archive_mode"] == "append"
    after = ib.parse_board(out["archive_plan"]["final_text"])
    assert after["header"]["archive"] is True
    assert after["warnings"] == []
    assert [i["number"] for i in after["issues"]] == [4, 9]


def test_archive_refuses_board_and_duplicates_and_empty():
    with pytest.raises(ib.BoardError):
        ib.plan_archive(SAMPLE, "DONE", archive_text=SAMPLE)
    first = ib.plan_archive(SAMPLE, "DONE")
    with pytest.raises(ib.BoardError):
        ib.plan_archive(SAMPLE, "DONE", archive_text=first["archive_plan"]["final_text"])
    # SAMPLE has no IN PROGRESS issue besides #1; use a board with no DONE.
    no_done = SAMPLE.replace("#4 [DONE]", "#4 [OPEN]")
    with pytest.raises(ib.BoardError):
        ib.plan_archive(no_done, "DONE")
    with pytest.raises(ib.BoardError):
        ib.plan_archive(SAMPLE, "CLOSED")


def test_archive_parent_warning():
    variant = SAMPLE.replace("#3 [OPEN]", "#3 [DONE]")
    out = ib.plan_archive(variant, "DONE")
    assert out["archived"] == [3, 4]
    assert out["parent_warnings"] == ["#1 has parent #3, which moves to the archive"]


def test_cli_archive_create_and_append(tmp_path, capsys):
    note = note_file(tmp_path, SAMPLE)
    missing = os.path.join(str(tmp_path), "archive.json")
    code, out = run_cli(capsys, ["archive", note, missing])
    assert code == 0 and out["archive_mode"] == "create" and out["archived"] == [4]
    archive = write_json(tmp_path, "archive2.json",
                         {"note": {"text": out["archive_plan"]["final_text"], "formats": []}})
    variant = SAMPLE.replace("#1 [IN PROGRESS]", "#1 [DONE]").replace("#4 [DONE]", "#4 [OPEN]")
    note2 = note_file(tmp_path, variant)
    code, out = run_cli(capsys, ["archive", note2, archive])
    assert code == 0 and out["archive_mode"] == "append" and out["archived"] == [1]


# ---------------------------------------------------------------- replace

def test_replace_finding_block():
    plan = ib.plan_replace_field(SAMPLE, 2, "finding",
                                 [["2 views have 500+ 2D elements:",
                                   "View C (id2003): 900 - 800 lines"]])
    ft = apply(SAMPLE, plan)
    assert ft.text == plan["final_text"]
    i2 = ib.find_issue(ib.parse_board(ft.text), 2)
    assert i2["findings"] == ["2 views have 500+ 2D elements:",
                              "View C (id2003): 900 - 800 lines"]
    assert i2["todos"] == ["delete or simplify."]
    assert i2["severity"] == ["High"]
    assert ib.parse_board(ft.text)["warnings"] == []


def test_replace_todo_block_keeps_finding():
    plan = ib.plan_replace_field(SAMPLE, 2, "todo", ["delete, then purge."])
    i2 = ib.find_issue(ib.parse_board(plan["final_text"]), 2)
    assert i2["todos"] == ["delete, then purge."]
    assert len(i2["findings"]) == 3


def test_replace_keeps_related_and_comments():
    plan = ib.plan_replace_field(SAMPLE, 1, "finding", ["new finding (id1009)."])
    i1 = ib.find_issue(ib.parse_board(plan["final_text"]), 1)
    assert i1["findings"] == ["new finding (id1009)."]
    assert i1["comments"][0]["text"] == "moved to the links workset; pinned."
    assert i1["related"] == [3] and i1["parent"] == 3
    kinds = [ln["kind"] for ln in i1["lines"]]
    assert kinds == ["finding", "todo", "comment", "related"]


def test_replace_rejects_bad_input():
    with pytest.raises(ib.BoardError):
        ib.plan_replace_field(SAMPLE, 4, "finding", ["x"])  # #4 has no Finding block
    with pytest.raises(ib.BoardError):
        ib.plan_replace_field(SAMPLE, 2, "severity", ["x"])
    with pytest.raises(ib.BoardError):
        ib.plan_replace_field(SAMPLE, 2, "todo", [])
    with pytest.raises(ib.BoardError):
        ib.plan_replace_field(SAMPLE, 2, "todo", ["two\rparagraphs"])
    with pytest.raises(ib.BoardError):
        ib.plan_replace_field(SAMPLE, 9, "todo", ["x"])


def test_cli_replace(tmp_path, capsys):
    note = note_file(tmp_path, SAMPLE)
    lines = write_json(tmp_path, "lines.json", {"lines": ["delete, then purge."]})
    code, plan = run_cli(capsys, ["replace", note, "2", "todo", lines])
    assert code == 0
    ft = apply(SAMPLE, plan)
    assert ib.find_issue(ib.parse_board(ft.text), 2)["todos"] == ["delete, then purge."]
    assert board_cli.main(["replace", note, "2", "nope", lines]) == 2


# ---------------------------------------------------------------- recheck

def test_recheck_inventory_and_suggestions():
    board = ib.parse_board(SAMPLE)
    assert ib.recheck_inventory(board) == {1: [1001], 2: [2001, 2002], 3: [1001]}
    out = ib.format_recheck_suggestions([
        {"number": 1, "id": 1001, "exists": True, "kind": "CAD link", "detail": "sample.dwg"},
        {"number": 2, "id": 2001, "exists": True, "kind": "Element", "detail": "Views"},
        {"number": 2, "id": 2002, "exists": False, "kind": "", "detail": ""}])
    assert out == [
        {"number": 1, "comment": "Recheck: id1001 exists (CAD link, sample.dwg)."},
        {"number": 2, "comment": "Recheck: id2001 exists (Element, Views); id2002 is missing."}]


def test_archive_note_is_not_a_board():
    out = ib.plan_archive(SAMPLE, "DONE")
    archive = ib.parse_board(out["archive_plan"]["final_text"])
    assert archive["header"]["next_number"] is None
    assert archive["warnings"] == []

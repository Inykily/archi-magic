import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path[:0] = [str(HERE), str(SCRIPTS)]

import vba_fixture as fx  # noqa: E402
import vba_project as vp  # noqa: E402

CLI = SCRIPTS / "vba_project.py"
APPLY = SCRIPTS / "vba_apply.ps1"


def run_cli(*args):
    return subprocess.run([sys.executable, str(CLI)] + [str(a) for a in args],
                          capture_output=True, text=True, encoding="utf-8")


@pytest.fixture
def xlsm(tmp_path):
    return fx.build_xlsm(str(tmp_path / "Book A.xlsm"), fx.SAMPLE_MODULES)


# --- compression -----------------------------------------------------------

def test_decompress_spec_example_without_copy_tokens():
    # [MS-OVBA] 3.2.1: a chunk of literals only.
    data = bytes.fromhex("0119B000616263646566676800696A6B6C6D6E6F7000717273747576" "2E")
    assert vp.decompress(data) == b"abcdefghijklmnopqrstuv."


@pytest.mark.parametrize("raw", [False, True])
def test_compress_round_trip_over_several_chunks(raw):
    rng = random.Random(7)
    words = [b"Dim ", b"As Long", b"\r\n", b"keyText", b"Next i", b" = ", b"ws.Cells(i, 1)"]
    text = b"".join(rng.choice(words) for _ in range(4000)) + bytes(rng.randrange(256) for _ in range(3000))
    packed = fx.compress(text, raw_full_chunks=raw)
    assert len(text) > 3 * 4096
    assert vp.decompress(packed) == text


def test_decompress_rejects_bad_input():
    with pytest.raises(vp.VbaError):
        vp.decompress(b"\x02\x00")
    with pytest.raises(vp.VbaError):
        vp.decompress(b"\x01\x05\x80\x01\x00\x00")  # bad chunk signature


# --- reading ----------------------------------------------------------------

def test_load_project_reads_every_module_kind_and_hides_attributes(xlsm):
    project = vp.load_project(xlsm)
    assert [(m["name"], m["kind"], m["extension"]) for m in project["modules"]] == [
        ("ThisWorkbook", "document", ".cls"), ("Keynotes", "module", ".bas"), ("KeyItem", "class", ".cls")]
    keynotes = project["modules"][1]
    assert keynotes["source"][0].startswith("Attribute VB_Name")
    assert keynotes["code"][0] == "Option Explicit"
    assert "Public Sub ExportKeys()" in keynotes["code"]
    assert project["codepage"] == 1252


def test_load_project_reads_old_xls_compound_file(tmp_path):
    path = fx.build_xls(str(tmp_path / "old.xls"), fx.SAMPLE_MODULES)
    assert [m["name"] for m in vp.load_project(path)["modules"]] == ["ThisWorkbook", "Keynotes", "KeyItem"]


def test_large_module_uses_regular_sectors(tmp_path):
    body = "".join("    total = total + %d ' line %d\r\n" % (i, i) for i in range(900))
    modules = [("Big", "module", "Attribute VB_Name = \"Big\"\r\nSub Run()\r\n" + body + "End Sub\r\n")]
    path = fx.build_xlsm(str(tmp_path / "big.xlsm"), modules, raw_full_chunks=True)
    code = vp.load_project(path)["modules"][0]["code"]
    assert len(code) == 902 and code[-2] == "    total = total + 899 ' line 899"


def test_non_ascii_text_uses_the_project_code_page(tmp_path):
    modules = [("M1", "module", "Attribute VB_Name = \"M1\"\r\n' Façade °C\r\n")]
    path = fx.build_xlsm(str(tmp_path / "cp.xlsm"), modules)
    assert vp.load_project(path)["modules"][0]["code"] == ["' Façade °C"]


def test_plain_xlsx_has_no_vba_project(tmp_path):
    import zipfile
    path = tmp_path / "plain.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(vp.VbaError, match="no VBA project"):
        vp.load_project(str(path))
    result = run_cli("dump", path)
    assert result.returncode == 2 and "no VBA project" in result.stderr


def test_dump_cli_prints_modules_and_writes_files_to_new_folder(xlsm, tmp_path):
    result = run_cli("dump", xlsm, "--numbers")
    assert result.returncode == 0
    assert "' ===== Keynotes (module, 24 lines) =====" in result.stdout
    assert "    1  Option Explicit" in result.stdout
    out = tmp_path / "modules"
    result = run_cli("dump", xlsm, "--out", out)
    assert result.returncode == 0
    assert sorted(os.listdir(out)) == ["KeyItem.cls", "Keynotes.bas", "ThisWorkbook.cls"]
    again = run_cli("dump", xlsm, "--out", out)
    assert again.returncode == 2 and "not empty" in again.stderr


# --- scan -------------------------------------------------------------------

def test_scan_finds_undeclared_assignment_targets_only(xlsm):
    result = vp.scan_project(vp.load_project(xlsm))
    names = [(f["module"], f["name"], f["line"]) for f in result["undeclared"]]
    assert names == [("Keynotes", "i", 10), ("Keynotes", "keyText", 11), ("Keynotes", "skipped", 12),
                     ("Keynotes", "ExportKeys_Count", 16), ("KeyItem", "total", 4)]
    assert result["modules_without_option_explicit"] == ["KeyItem"]
    flagged = {f["name"].lower() for f in result["undeclared"]}
    # Declared, module-level, parameters, function result, class member and Excel globals stay quiet.
    assert not flagged & {"ws", "lastrow", "mcount", "keycount", "n", "stop_at", "key", "cells"}


def test_logical_statements_join_continuations_and_ignore_strings():
    lines = ['x = "a: b = 1" : y = 2 \' c: d = 3', "z = _", "  4", "Foo a:=1"]
    assert list(vp.logical_statements(lines)) == [(1, 'x = ""'), (1, "y = 2"), (2, "z =    4"), (4, "Foo a:=1")]


# --- plan, apply model, verify ---------------------------------------------

def write_edits(tmp_path, edits):
    path = tmp_path / "edits.json"
    path.write_text(json.dumps({"edits": edits}), encoding="utf-8")
    return path


def test_plan_resolves_edits_previews_diff_and_never_touches_source(xlsm, tmp_path):
    before = vp.sha256_file(xlsm)
    edits = write_edits(tmp_path, [
        {"module": "Keynotes", "action": "insert_after", "match": "    Dim ws As Worksheet, lastRow As Long",
         "lines": ["    Dim i As Long, keyText As String, skipped As Long"]},
        {"module": "Keynotes", "action": "replace", "match": "        mCount = mCount + 1",
         "lines": ["        mCount = mCount + 2"]},
        {"module": "KeyItem", "action": "insert_before", "match": "Public Key As String", "lines": ["Option Explicit"]},
    ])
    plan_path = tmp_path / "plan.json"
    result = run_cli("plan", xlsm, "--edits", edits, "--out", plan_path)
    assert result.returncode == 0, result.stderr
    assert "+    Dim i As Long, keyText As String, skipped As Long" in result.stdout
    assert "-        mCount = mCount + 1" in result.stdout
    assert vp.sha256_file(xlsm) == before
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["source_sha256"] == before
    assert [(s["module"], s["line"]) for s in plan["steps"]] == [("Keynotes", 13), ("Keynotes", 7), ("KeyItem", 1)]
    assert plan["modules"]["Keynotes"]["code_lines"] == 24
    code = plan["expected_code"]["Keynotes"]
    assert code[7] == "    Dim i As Long, keyText As String, skipped As Long"
    assert code[13] == "        mCount = mCount + 2"
    assert plan["expected_code"]["KeyItem"][0] == "Option Explicit"
    again = run_cli("plan", xlsm, "--edits", edits, "--out", plan_path)
    assert again.returncode == 2 and "already exists" in again.stderr


@pytest.mark.parametrize("edit, message", [
    ({"module": "Nope", "action": "delete", "match": "x"}, "not in the workbook"),
    ({"module": "Keynotes", "action": "move", "match": "x"}, "action must be"),
    ({"module": "Keynotes", "action": "delete", "match": "not a line"}, "no line of Keynotes"),
    ({"module": "Keynotes", "action": "delete", "match": ""}, "exact text"),
    ({"module": "Keynotes", "action": "insert_after", "match": "Option Explicit", "lines": ["a\nb"]}, "line break"),
    ({"module": "Keynotes", "action": "insert_after", "match": "Option Explicit", "lines": []}, "at least one"),
    ({"module": "Keynotes", "action": "insert_after", "match": "Option Explicit",
      "lines": ["Attribute X.VB_Description = \"\""]}, "Attribute"),
    ({"module": "Keynotes", "action": "insert_after", "match": "Option Explicit", "lines": ["' 中"]}, "code page"),
    ({"module": "Keynotes", "action": "delete", "match": "End Sub", "line": 3}, "does not hold"),
])
def test_plan_rejects_unsafe_or_ambiguous_edits(xlsm, edit, message):
    project = vp.load_project(xlsm)
    with pytest.raises(vp.VbaError, match=message):
        vp.build_plan(project, "0" * 64, [edit])


def test_plan_needs_line_for_repeated_text_and_rejects_shared_anchor(xlsm, tmp_path):
    twice = [("M1", "module", "Sub A()\r\nEnd Sub\r\nSub B()\r\nEnd Sub\r\n")]
    project = vp.load_project(fx.build_xlsm(str(tmp_path / "twice.xlsm"), twice))
    with pytest.raises(vp.VbaError, match=r"on 2 lines \[2, 4\]; add 'line'"):
        vp.build_plan(project, "0", [{"module": "M1", "action": "delete", "match": "End Sub"}])
    plan = vp.build_plan(project, "0", [{"module": "M1", "action": "delete", "match": "End Sub", "line": 4}])
    assert plan["steps"][0]["line"] == 4
    project = vp.load_project(xlsm)
    with pytest.raises(vp.VbaError, match="combine"):
        vp.build_plan(project, "0", [
            {"module": "Keynotes", "action": "insert_after", "match": "Option Explicit", "lines": ["' a"]},
            {"module": "Keynotes", "action": "insert_before", "match": "Option Explicit", "lines": ["' b"]}])


def test_descending_steps_match_editing_the_lines_one_by_one(xlsm):
    project = vp.load_project(xlsm)
    plan = vp.build_plan(project, "0", [
        {"module": "Keynotes", "action": "insert_after", "match": "Option Explicit", "lines": ["' after 1"]},
        {"module": "Keynotes", "action": "delete", "match": "Private mCount As Long"},
        {"module": "Keynotes", "action": "replace", "match": "End Function", "lines": ["End Function", "' tail"]},
    ])
    code = plan["expected_code"]["Keynotes"]
    assert code[:3] == ["Option Explicit", "' after 1", ""]
    assert "Private mCount As Long" not in code
    assert code[-2:] == ["End Function", "' tail"]
    assert len(code) == 24 + 1 - 1 + 1


def make_edited_copy(tmp_path, plan, rewrite=None):
    """Build the copy that Excel would save: the planned code, optionally reformatted."""
    modules = []
    for name, kind, text in fx.SAMPLE_MODULES:
        if name in plan["expected_code"]:
            lines = plan["expected_code"][name]
            if rewrite:
                lines = [rewrite(line) for line in lines]
            text = 'Attribute VB_Name = "%s"\r\n' % name + "".join(line + "\r\n" for line in lines)
        modules.append((name, kind, text))
    return fx.build_xlsm(str(tmp_path / "Book A (fixed).xlsm"), modules)


def test_verify_accepts_editor_reformatting_and_reports_differences(xlsm, tmp_path):
    edits = write_edits(tmp_path, [{"module": "Keynotes", "action": "insert_after",
                                    "match": "    Dim ws As Worksheet, lastRow As Long", "lines": ["    dim i as long"]}])
    plan_path = tmp_path / "plan.json"
    assert run_cli("plan", xlsm, "--edits", edits, "--out", plan_path).returncode == 0
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    copy = make_edited_copy(tmp_path, plan, rewrite=lambda l: l.replace("dim i as long", "Dim i As Long"))
    result = run_cli("verify", plan_path, "--file", copy)
    assert result.returncode == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["all_match"] and report["source_unchanged"] and report["modules"][0]["exact"] is False

    os.remove(copy)
    copy = make_edited_copy(tmp_path, plan, rewrite=lambda l: l.replace("dim i as long", "Dim j As Long"))
    result = run_cli("verify", plan_path, "--file", copy)
    assert result.returncode == 1
    assert json.loads(result.stdout)["modules"][0]["status"] == "different"

    result = run_cli("verify", plan_path, "--file", xlsm)
    assert result.returncode == 2 and "not the source" in result.stderr


# --- find -------------------------------------------------------------------

def test_find_is_shallow_and_lists_only_macro_workbooks(tmp_path):
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    for rel in ["Keys.xlsm", "a/Old.xls", "a/b/Addin.xlam", "a/b/c/Deep.xlsm", "plain.xlsx", "~$Keys.xlsm"]:
        (tmp_path / rel).write_bytes(b"x")
    result = vp.find_workbooks([str(tmp_path)], depth=3)
    names = sorted(os.path.basename(r["path"]) for r in result["files"])
    assert names == ["Addin.xlam", "Keys.xlsm", "Old.xls"]
    assert result["complete"] is True
    assert [os.path.basename(r["path"]) for r in vp.find_workbooks([str(tmp_path)], "keys")["files"]] == ["Keys.xlsm"]


def test_find_stops_at_the_time_limit(tmp_path):
    ticks = iter(range(100))
    result = vp.find_workbooks([str(tmp_path)], seconds=0, clock=lambda: next(ticks))
    assert result["complete"] is False


# --- vba_apply.ps1 input checks (stop before Excel) ------------------------

POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")


def run_apply(*args):
    return subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(APPLY)] +
                          [str(a) for a in args], capture_output=True, text=True)


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell is not installed")
def test_apply_refuses_unsafe_outputs_and_a_changed_source(xlsm, tmp_path):
    edits = write_edits(tmp_path, [{"module": "KeyItem", "action": "insert_before",
                                    "match": "Public Key As String", "lines": ["Option Explicit"]}])
    plan_path = tmp_path / "plan.json"
    assert run_cli("plan", xlsm, "--edits", edits, "--out", plan_path).returncode == 0

    result = run_apply("-Plan", plan_path, "-Output", xlsm)
    assert result.returncode == 2 and "source workbook" in result.stdout

    existing = tmp_path / "exists.xlsm"
    existing.write_bytes(b"x")
    result = run_apply("-Plan", plan_path, "-Output", existing)
    assert result.returncode == 2 and "already exists" in result.stdout

    result = run_apply("-Plan", plan_path, "-Output", tmp_path / "copy.xlsx")
    assert result.returncode == 2 and "same extension" in result.stdout

    with open(xlsm, "ab") as handle:
        handle.write(b"\x00")
    target = tmp_path / "copy.xlsm"
    result = run_apply("-Plan", plan_path, "-Output", target)
    assert result.returncode == 2 and "changed after the preview" in result.stdout
    assert not target.exists()

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import compile_set as cs  # noqa: E402
import read_sheet_list as rsl  # noqa: E402

pypdf = pytest.importorskip("pypdf")


def make_pdf(path, pages=1, mtime=None):
    w = pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=72 * 36, height=72 * 24)
    with open(path, "wb") as fh:
        w.write(fh)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


SHEETS = [
    {"sheet": "T-001", "title": "Title Sheet"},
    {"sheet": "G-001", "title": "General Notes"},
    {"sheet": "G-002", "title": "Life Safety"},
    {"sheet": "A-101", "title": "Plan"},
]


@pytest.mark.parametrize("name,expected", [
    ("A-101 FIRST FLOOR PLAN.pdf", ("A-101", "FIRST FLOOR PLAN")),
    ("A-101-FIRST FLOOR PLAN.pdf", ("A-101", "FIRST FLOOR PLAN")),
    ("A-101 - FIRST FLOOR PLAN.pdf", ("A-101", "FIRST FLOOR PLAN")),
    ("A-370 - DETAILS - DOORS.pdf", ("A-370", "DETAILS - DOORS")),
    ("dm-100 demo plan.pdf", ("DM-100", "demo plan")),
    ("notes.pdf", None),
])
def test_parse_name(name, expected):
    assert cs.parse_name(name) == expected


def test_newest_wins_unlisted_left_out_missing_reported(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_pdf(src / "T-001 TITLE SHEET.pdf")
    make_pdf(src / "G-001 OLD NOTES.pdf", mtime=1_000_000)
    make_pdf(src / "G-001-NEW NOTES.pdf", mtime=2_000_000)
    make_pdf(src / "A-101 PLAN.pdf")
    make_pdf(src / "A-999 NOT IN LIST.pdf")
    files, unparsed = cs.scan_folder(str(src))
    plan, missing, dups, excluded = cs.build_plan(SHEETS, files)
    assert [p["sheet"] for p in plan] == ["T-001", "G-001", "A-101"]
    assert plan[1]["file"] == "G-001-NEW NOTES.pdf"
    assert plan[1]["bookmark"] == "G-001 NEW NOTES"
    assert missing == ["G-002 Life Safety"]
    assert dups[0]["ignored"] == ["G-001 OLD NOTES.pdf"]
    assert excluded == ["A-999 NOT IN LIST.pdf"]


def test_compile_verify_refuse_overwrite_and_diff(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    for s in SHEETS:
        make_pdf(src / ("%s %s.pdf" % (s["sheet"], s["title"].upper())), mtime=1_000_000)
    sheets = tmp_path / "sheets.json"
    sheets.write_text(json.dumps(SHEETS), encoding="utf-8")
    out = tmp_path / "out" / "Set.pdf"
    out.parent.mkdir()
    args = [str(src), str(sheets), str(out)]

    assert cs.main(args + ["--dry"]) == 0
    assert not out.exists()
    assert cs.main(args) == 0
    r = pypdf.PdfReader(str(out))
    assert len(r.pages) == 4
    assert [o.title for o in r.outline] == ["T-001 TITLE SHEET", "G-001 GENERAL NOTES", "G-002 LIFE SAFETY", "A-101 PLAN"]
    assert "VERIFY    pages 4, bookmarks 4, plan 4, OK" in capsys.readouterr().out

    # Second run without --overwrite must stop and keep the file.
    before = out.read_bytes()
    assert cs.main(args) == 4
    assert out.read_bytes() == before

    # Update one sheet, add a hyphen-named newer copy: diff reports it, overwrite rebuilds.
    make_pdf(src / "A-101-PLAN REV.pdf", mtime=2_000_000)
    assert cs.main(args + ["--overwrite"]) == 0
    text = capsys.readouterr().out
    assert "UPDATED  A-101" in text
    assert "RENAMED  bookmark 'A-101 PLAN' -> 'A-101 PLAN REV'" in text
    assert pypdf.PdfReader(str(out)).outline[3].title == "A-101 PLAN REV"


@pytest.mark.parametrize("raw,expected", [
    ("_ENLARGED PLANS-SHARED LOUNGES B", "ENLARGED PLANS-SHARED LOUNGES B"),
    ("- MILLWORK DETAILS - LIBRARY", "MILLWORK DETAILS - LIBRARY"),
    ("MEZZANINE  PLAN", "MEZZANINE PLAN"),
    ("9th FLOOR FURNITURE PLAN", "9TH FLOOR FURNITURE PLAN"),
])
def test_normalize_title(raw, expected):
    assert cs.normalize_title(raw) == expected


def test_fallback_folder_and_user_exclude(tmp_path, capsys):
    main, old = tmp_path / "main", tmp_path / "old"
    main.mkdir()
    old.mkdir()
    make_pdf(main / "T-001 TITLE SHEET.pdf", mtime=2_000_000)
    make_pdf(old / "T-001 TITLE SHEET.pdf", mtime=3_000_000)  # newer, but main folder wins
    make_pdf(old / "G-001 _GENERAL  NOTES.pdf")
    make_pdf(main / "A-101 PLAN.pdf")
    sheets = tmp_path / "s.json"
    sheets.write_text(json.dumps(SHEETS), encoding="utf-8")
    out = tmp_path / "set.pdf"
    rc = cs.main([str(main), str(sheets), str(out), "--fallback", str(old), "--exclude", "g-002"])
    assert rc == 0
    text = capsys.readouterr().out
    assert "REMOVED BY USER  G-002" in text
    assert "FALLBACK  G-001" in text
    assert "MISSING" not in text
    assert [o.title for o in pypdf.PdfReader(str(out)).outline] == ["T-001 TITLE SHEET", "G-001 GENERAL NOTES", "A-101 PLAN"]


def test_multi_page_source_stops(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_pdf(src / "T-001 TITLE.pdf", pages=2)
    sheets = tmp_path / "s.json"
    sheets.write_text(json.dumps(SHEETS[:1]), encoding="utf-8")
    assert cs.main([str(src), str(sheets), str(tmp_path / "o.pdf")]) == 6
    assert not (tmp_path / "o.pdf").exists()


def test_diff_manifest_order_and_removed():
    old = [{"sheet": "A", "file": "a", "mtime": "1", "bookmark": "A x"},
           {"sheet": "B", "file": "b", "mtime": "1", "bookmark": "B y"}]
    new = [{"sheet": "B", "file": "b", "mtime": "1", "bookmark": "B y"},
           {"sheet": "C", "file": "c", "mtime": "2", "bookmark": "C z"}]
    lines = cs.diff_manifest(old, new)
    assert any(l.startswith("ADDED    C") for l in lines)
    assert any(l.startswith("REMOVED  A") for l in lines)


def test_sheet_list_extract_and_columns():
    rows = [
        (None, None, "2026-01-01", "2026-02-01"),
        (None, None, "SD", "CD"),
        (None, None, None, "Issued for Bid"),
        ("T Series", "Title", None, None),
        ("T-001", "Title Sheet", "X", "X"),
        ("G-001", "Notes", "X", None),
        ("A-101", "Plan", None, "x"),
    ]
    got = rsl.extract(rows, number_col=0, title_col=1, mark_col=3)
    assert [g["sheet"] for g in got] == ["T-001", "A-101"]
    assert got[0]["row"] == 5
    assert rsl.col_index("M") == 12 and rsl.col_index("AA") == 26
    assert rsl.col_letter(12) == "M" and rsl.col_letter(26) == "AA"


def test_sheet_list_from_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DRAWINGS"
    for r in [(None, None, "SD", "CD"), (None, None, None, None), (None, None, None, None),
              ("T-001", "Title", "X", "X"), ("A-101", "Plan", None, "X")]:
        ws.append(r)
    p = tmp_path / "list.xlsx"
    wb.save(p)
    out = tmp_path / "s.json"
    assert rsl.main([str(p), "--tab", "DRAWINGS", "--number-col", "A", "--title-col", "B",
                     "--mark-col", "D", "--json", str(out)]) == 0
    assert [s["sheet"] for s in json.loads(out.read_text(encoding="utf-8"))] == ["T-001", "A-101"]

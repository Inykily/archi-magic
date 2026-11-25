"""Read a drawing list (sheet list) from Excel and write the sheets of one issue column as JSON.

Usage:
  python read_sheet_list.py --check
  python read_sheet_list.py <list.xlsx> --columns [--tab NAME]
      Prints each tab, its size, and the header rows of every column, so the user can pick
      the issue column.
  python read_sheet_list.py <list.xlsx> --tab NAME --number-col B --title-col C --mark-col M
      --json <out.json> [--header-rows 3]
      Writes [{"row", "sheet", "title", "mark"}] for every row with a sheet number and a
      non-empty cell in the mark column. Rows whose number contains "Series" are group headers
      and are skipped. The order is the order of the rows in the list.
  python read_sheet_list.py <list.xlsx> --tab NAME --number-col B --title-col C --all-rows
      --json <out.json> [--group-col A] [--header-rows 1]
      For a list made only for this set: every row with a sheet number goes in (no mark column).
      --group-col carries the last non-empty value down (for example a discipline name) into
      "group", for the source chart. With --all-rows, a row whose number cell does not look like a
      sheet number (letters, an optional separator, digits) is a group header: it is skipped,
      printed as GROUP HEADER, and its text goes into "group" when there is no --group-col.
  python read_sheet_list.py <list.xlsx> --tab NAME --block B:C --block I:J --all-rows --json <out.json>
      A list with two or more column blocks side by side. Give one --block NUMBER:TITLE (or
      NUMBER:TITLE:MARK) per block, in reading order. The blocks go into one JSON in that order,
      and each item gets "block" (1, 2, ...).

The file is opened read-only. Nothing in the workbook changes.
Exit codes: 0 ok, 2 bad arguments or bad file, 3 openpyxl is missing.
"""
import argparse
import datetime
import json
import re
import sys

SHEET_LIKE = re.compile(r"^[A-Z]{1,4}[\s\-._]?\d[0-9A-Z.\-]*$", re.I)


def col_index(letter):
    """'A' -> 0, 'M' -> 12, 'AA' -> 26."""
    n = 0
    for ch in letter.strip().upper():
        if not "A" <= ch <= "Z":
            raise ValueError("bad column letter: " + letter)
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def col_letter(index):
    s = ""
    index += 1
    while index:
        index, r = divmod(index - 1, 26)
        s = chr(65 + r) + s
    return s


def cell_text(v):
    if v is None:
        return ""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def looks_like_sheet(text):
    """'A-101', 'FS1.0', 'TA-101M', 'A101' -> True. 'GENERAL', 'T Series' -> False."""
    return bool(SHEET_LIKE.match(text or ""))


def extract(rows, number_col, title_col, mark_col, header_rows=3, group_col=None, headers=None):
    """Return the marked sheets from a list of row tuples (pure logic, used by the tests).
    mark_col None means every row with a sheet number. Then a number cell that does not look
    like a sheet number is a group header: it is skipped, added to headers as (row, text), and
    becomes "group" when there is no group_col."""
    out = []
    group = ""
    for i, r in enumerate(rows, start=1):
        if i <= header_rows:
            continue
        get = lambda c: cell_text(r[c]) if c is not None and c < len(r) else ""
        if group_col is not None and get(group_col):
            group = get(group_col)
        num = get(number_col)
        if mark_col is None and num and not looks_like_sheet(num):
            if headers is not None:
                headers.append((i, num))
            if group_col is None:
                group = num
            continue
        mark = num if mark_col is None else get(mark_col)
        if not num or not mark or "series" in num.lower():
            continue
        item = {"row": i, "sheet": num, "title": get(title_col), "mark": mark}
        if group_col is not None or mark_col is None:
            item["group"] = group
        out.append(item)
    return out


def parse_block(text, mark_default=None):
    """'B:C' -> (1, 2, mark_default), 'B:C:M' -> (1, 2, 12). Letters to 0-based indexes."""
    parts = [p for p in text.split(":") if p.strip()]
    if len(parts) not in (2, 3):
        raise ValueError("a block is NUMBER:TITLE or NUMBER:TITLE:MARK, for example B:C")
    mark = col_index(parts[2]) if len(parts) == 3 else mark_default
    return col_index(parts[0]), col_index(parts[1]), mark


def extract_blocks(rows, blocks, header_rows=3, group_col=None, headers=None):
    """Pure logic: read each (number, title, mark) block in order into one list. Each item gets
    "block" (1-based) when there is more than one block. headers: {block: [(row, text)]}."""
    out = []
    for k, (num, title, mark) in enumerate(blocks, start=1):
        got = extract(rows, num, title, mark, header_rows, group_col,
                      None if headers is None else headers.setdefault(k, []))
        if len(blocks) > 1:
            for g in got:
                g["block"] = k
        out += got
    return out


def sheet_columns(rows, header_rows=3, at_least=3):
    """Pure logic: the column indexes with at least `at_least` cells that look like sheet numbers."""
    count = {}
    for r in rows[header_rows:]:
        for c, v in enumerate(r):
            if looks_like_sheet(cell_text(v)):
                count[c] = count.get(c, 0) + 1
    return sorted(c for c, n in count.items() if n >= at_least)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--columns", action="store_true")
    ap.add_argument("--tab")
    ap.add_argument("--number-col")
    ap.add_argument("--title-col")
    ap.add_argument("--mark-col")
    ap.add_argument("--all-rows", action="store_true", help="no mark column: every row with a sheet number")
    ap.add_argument("--group-col")
    ap.add_argument("--block", action="append", default=[],
                    help="NUMBER:TITLE[:MARK] column letters of one block (repeat, in reading order)")
    ap.add_argument("--header-rows", type=int, default=3)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # file names can hold characters the Windows console code page lacks
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        import openpyxl
    except ImportError:
        print("openpyxl is missing. Install it with: python -m pip install --user openpyxl")
        return 3
    if a.check:
        print("openpyxl", openpyxl.__version__)
        return 0
    if not a.xlsx:
        ap.print_usage()
        return 2
    wb = openpyxl.load_workbook(a.xlsx, read_only=True, data_only=True)
    if a.columns:
        tabs = [wb[a.tab]] if a.tab else wb.worksheets
        for ws in tabs:
            rows = list(ws.iter_rows(max_row=a.header_rows, values_only=True))
            print("TAB", ws.title, "rows", ws.max_row, "cols", ws.max_column)
            width = max((len(r) for r in rows), default=0)
            for c in range(width):
                head = " | ".join(cell_text(r[c]) for r in rows if c < len(r) and cell_text(r[c]))
                if head:
                    print("  col", col_letter(c), ":", head)
            nums = sheet_columns(list(ws.iter_rows(values_only=True)), a.header_rows)
            if len(nums) > 1:
                print("  HINT  sheet numbers in columns %s: the list may have more than one block. "
                      "Use --block NUMBER:TITLE once per block, for example %s." % (
                          ", ".join(col_letter(c) for c in nums),
                          " ".join("--block %s:%s" % (col_letter(c), col_letter(c + 1)) for c in nums)))
        return 0
    if not (a.tab and (a.number_col or a.block) and (a.mark_col or a.all_rows or a.block) and a.json):
        print("Give --tab, --number-col (or --block), --mark-col (or --all-rows) and --json (and --title-col).")
        return 2
    ws = wb[a.tab]
    rows = list(ws.iter_rows(values_only=True))
    mark = None if a.all_rows else (col_index(a.mark_col) if a.mark_col else None)
    try:
        if a.block:
            blocks = [parse_block(b, mark) for b in a.block]
            if a.all_rows:
                blocks = [(n, t, None) for n, t, _ in blocks]
        else:
            title_col = col_index(a.title_col) if a.title_col else col_index(a.number_col) + 1
            blocks = [(col_index(a.number_col), title_col, mark)]
    except ValueError as e:
        print("Bad column:", e)
        return 2
    if not a.all_rows and any(b[2] is None for b in blocks):
        print("Give --mark-col, NUMBER:TITLE:MARK blocks, or --all-rows.")
        return 2
    group = col_index(a.group_col) if a.group_col else None
    headers = {}
    sheets = extract_blocks(rows, blocks, a.header_rows, group, headers)
    mark = blocks[0][2]
    head = "(all rows)" if mark is None else " | ".join(
        cell_text(rows[r][mark]) for r in range(min(a.header_rows, len(rows))) if mark < len(rows[r]) and cell_text(rows[r][mark]))
    with open(a.json, "w", encoding="utf-8") as fh:
        json.dump(sheets, fh, indent=1, ensure_ascii=False)
    print("column", "-" if mark is None else col_letter(mark), "header:", head)
    for k, (num, title, _) in enumerate(blocks, start=1):
        if len(blocks) > 1:
            print("block %d %s:%s  sheets %d" % (k, col_letter(num), col_letter(title),
                                                 sum(s.get("block") == k for s in sheets)))
        for row, text in headers.get(k, []):
            print("GROUP HEADER  %d %s" % (row, text))
    print("marked sheets:", len(sheets))
    seen = {}
    for s in sheets:
        seen[s["sheet"].upper()] = seen.get(s["sheet"].upper(), 0) + 1
    dups = sorted(k for k, v in seen.items() if v > 1)
    if dups:
        print("WARNING: sheet numbers listed twice:", ", ".join(dups))
    return 0


if __name__ == "__main__":
    sys.exit(main())

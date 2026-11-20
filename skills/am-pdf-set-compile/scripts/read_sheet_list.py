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

The file is opened read-only. Nothing in the workbook changes.
Exit codes: 0 ok, 2 bad arguments or bad file, 3 openpyxl is missing.
"""
import argparse
import datetime
import json
import sys


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


def extract(rows, number_col, title_col, mark_col, header_rows=3):
    """Return the marked sheets from a list of row tuples (pure logic, used by the tests)."""
    out = []
    for i, r in enumerate(rows, start=1):
        if i <= header_rows:
            continue
        get = lambda c: cell_text(r[c]) if c < len(r) else ""
        num, mark = get(number_col), get(mark_col)
        if not num or not mark or "series" in num.lower():
            continue
        out.append({"row": i, "sheet": num, "title": get(title_col), "mark": mark})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--columns", action="store_true")
    ap.add_argument("--tab")
    ap.add_argument("--number-col")
    ap.add_argument("--title-col")
    ap.add_argument("--mark-col")
    ap.add_argument("--header-rows", type=int, default=3)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
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
        return 0
    if not (a.tab and a.number_col and a.mark_col and a.json):
        print("Give --tab, --number-col, --mark-col and --json (and --title-col).")
        return 2
    ws = wb[a.tab]
    rows = list(ws.iter_rows(values_only=True))
    title_col = col_index(a.title_col) if a.title_col else col_index(a.number_col) + 1
    sheets = extract(rows, col_index(a.number_col), title_col, col_index(a.mark_col), a.header_rows)
    head = " | ".join(cell_text(rows[r][col_index(a.mark_col)]) for r in range(min(a.header_rows, len(rows)))
                      if col_index(a.mark_col) < len(rows[r]) and cell_text(rows[r][col_index(a.mark_col)]))
    with open(a.json, "w", encoding="utf-8") as fh:
        json.dump(sheets, fh, indent=1, ensure_ascii=False)
    print("column", a.mark_col.upper(), "header:", head)
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

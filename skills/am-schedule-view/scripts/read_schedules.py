# -*- coding: utf-8 -*-
"""am-schedule-view: list or read Revit schedules exactly as Revit displays them. READ ONLY.

Run through the pyRevit agent runtime, query mode only:
  MCP:  run_query(script=<this file's text>, inputs={"mode": "read", "names": ["Door Schedule"]})
  CLI:  pyrevit agent run read_schedules.py --mode=query --revit=2026
        (no --inputs = list mode)

inputs (all optional):
  mode            "list" (default) or "read"
  names           schedule names to read (exact, case-insensitive)
  ids             schedule element ids to read (integers)
  maxRows         cap per schedule (default 5000)
  includeInternal true to also list/read revision, keynote and title-block schedules

Output (the `result` variable, JSON-compatible):
  list: {kind:"schedule-list", document, revitVersion, readAt,
         schedules:[{name,id,category,kind,rows,onSheet,sheets[]}], skipped:{...}}
  read: {kind:"schedules", document, revitVersion, readAt, rowKindSource:"heuristic",
         schedules:[{name,id,category,title,headerRows[][],columns[],rows[][],rowKinds[],
                     totalRows,truncated,note}], missing:[...]}
  rowKinds values: body | group | total | blank. Revit has no API for row kind; group and
  total rows are detected from the layout (merged cells, grand total title), so they are a heuristic.

Rules: IronPython 2.7 (no f-strings). Never modifies the model, never changes the active view.
"""
from pyrevit.api import DB
import datetime

try:
    INPUTS = inputs  # noqa: F821  (provided by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}

MODE = (INPUTS.get("mode") or "list").lower()
MAX_ROWS = int(INPUTS.get("maxRows") or 5000)
INCLUDE_INTERNAL = bool(INPUTS.get("includeInternal"))
WANT_NAMES = [unicode(n).strip().lower() for n in (INPUTS.get("names") or [])]  # noqa: F821
WANT_IDS = [int(i) for i in (INPUTS.get("ids") or [])]


def id_int(eid):
    # Revit 2024+ has ElementId.Value; older years have IntegerValue.
    v = getattr(eid, "Value", None)
    if v is None:
        v = eid.IntegerValue
    return int(v)


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def schedule_kind(vs):
    if safe(lambda: vs.IsTitleblockRevisionSchedule, False):
        return "revision"
    if safe(lambda: vs.IsInternalKeynoteSchedule, False):
        return "keynote"
    d = safe(lambda: vs.Definition)
    if d is not None:
        if safe(lambda: d.IsKeySchedule, False):
            return "key schedule"
        if safe(lambda: d.IsMaterialTakeoff, False):
            return "material takeoff"
    vt = safe(lambda: vs.ViewType)
    if vt is not None and str(vt) == "PanelSchedule":
        return "panel"
    cat = category_name(vs)
    if cat == "Sheets":
        return "sheet list"
    return "schedule"


def category_name(vs):
    d = safe(lambda: vs.Definition)
    if d is None:
        return ""
    cid = safe(lambda: d.CategoryId)
    if cid is None or id_int(cid) == -1:
        return "Multi-Category"
    cat = safe(lambda: DB.Category.GetCategory(doc, cid))  # noqa: F821
    return cat.Name if cat is not None else ""


def body_info(vs):
    td = vs.GetTableData()
    sec = td.GetSectionData(DB.SectionType.Body)
    return td, sec


def sheet_map():
    """schedule id -> sorted list of sheet numbers it is placed on (one collector)."""
    out = {}
    insts = DB.FilteredElementCollector(doc).OfClass(DB.ScheduleSheetInstance)  # noqa: F821
    for si in insts:
        if safe(lambda: si.IsTitleblockRevisionSchedule, False):
            continue
        sid = id_int(si.ScheduleId)
        sheet = doc.GetElement(si.OwnerViewId)  # noqa: F821
        num = safe(lambda: sheet.SheetNumber, "") if sheet is not None else ""
        out.setdefault(sid, set()).add(num)
    return dict((k, sorted(v)) for k, v in out.items())


def all_schedules():
    col = DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule)  # noqa: F821
    return [v for v in col if not v.IsTemplate]


def visible_headings(vs):
    d = vs.Definition
    heads = []
    for i in range(d.GetFieldCount()):
        f = d.GetField(i)
        if safe(lambda: f.IsHidden, False):
            continue
        heads.append(safe(lambda: f.ColumnHeading, "") or "")
    return heads


def cell(vs, section, r, c):
    # TableView.GetCellText returns the formatted text for every cell type (what Revit shows).
    t = safe(lambda: vs.GetCellText(section, r, c))
    if t is None:
        t = safe(lambda: section_data(vs, section).GetCellText(r, c), "")
    return t or ""


_SECTIONS = {}


def section_data(vs, section):
    key = (id_int(vs.Id), str(section))
    if key not in _SECTIONS:
        _SECTIONS[key] = vs.GetTableData().GetSectionData(section)
    return _SECTIONS[key]


def read_one(vs, sheets):
    d = vs.Definition
    td = vs.GetTableData()
    body = td.GetSectionData(DB.SectionType.Body)
    r0, r1 = body.FirstRowNumber, body.LastRowNumber
    c0, c1 = body.FirstColumnNumber, body.LastColumnNumber
    ncols = c1 - c0 + 1

    # Title from the Header section (the schedule title row), if the schedule shows one.
    title = ""
    head = safe(lambda: td.GetSectionData(DB.SectionType.Header))
    if head is not None and head.NumberOfRows > 0:
        title = " ".join(t for t in [cell(vs, DB.SectionType.Header, r, head.FirstColumnNumber)
                                      for r in range(head.FirstRowNumber, head.LastRowNumber + 1)] if t)

    # Column headings live in the first body rows when ShowHeaders is on. Find the row that
    # matches the visible field headings; rows above it are grouped (multi-row) headings.
    heads = safe(lambda: visible_headings(vs), [])
    show_headers = safe(lambda: d.ShowHeaders, True)
    header_rows = []
    header_spans = []
    columns = None
    data_start = r0
    if show_headers:
        # The last heading row is the first top row whose non-empty cells all equal the field
        # heading of their column. Rows above it hold grouped headings (Revit "Group Headers"),
        # which may also repeat a field heading that spans two rows.
        limit = min(r1, r0 + 6)
        matched = len(heads) == ncols
        for r in range(r0, limit + 1):
            texts = [cell(vs, DB.SectionType.Body, r, c) for c in range(c0, c1 + 1)]
            if matched:
                nonblank = [i for i, t in enumerate(texts) if t.strip()]
                if nonblank and all(texts[i].strip() == heads[i].strip() for i in nonblank):
                    columns = list(heads)
                    data_start = r + 1
                    break
            header_rows.append(texts)
        if columns is not None:
            # Keep only the group headings in headerRows; a field heading shows in columns.
            # headerSpans gives each group heading's width from Revit's merged cells.
            kept, spans = [], []
            for k, hr in enumerate(header_rows):
                row = [("" if t.strip() == heads[i].strip() else t) for i, t in enumerate(hr)]
                if not any(t.strip() for t in row):
                    continue
                r = r0 + k
                segs = []
                for i, t in enumerate(row):
                    if not t.strip():
                        continue
                    m = safe(lambda: body.GetMergedCell(r, c0 + i))
                    n = 1
                    if m is not None and m.Left <= c0 + i <= m.Right:
                        n = m.Right - (c0 + i) + 1
                    segs.append({"col": i, "span": n, "text": t})
                kept.append(row)
                spans.append(segs)
            header_rows = kept
            header_spans = spans
        if columns is None:
            # No exact match: take the first body row as headings (Revit's default layout).
            header_rows = []
            columns = [cell(vs, DB.SectionType.Body, r0, c) for c in range(c0, c1 + 1)]
            data_start = r0 + 1
    if columns is None:
        columns = heads if len(heads) == ncols else ["Column %d" % (i + 1) for i in range(ncols)]

    grand = safe(lambda: d.ShowGrandTotal, False)
    grand_title = (safe(lambda: d.GrandTotalTitle, "") or "").strip()
    has_footer = False
    for i in range(safe(lambda: d.GetSortGroupFieldCount(), 0)):
        if safe(lambda: d.GetSortGroupField(i).ShowFooter, False):
            has_footer = True

    total_rows = r1 - data_start + 1
    if total_rows < 0:
        total_rows = 0
    rows, kinds = [], []
    group_label = None
    last = min(r1, data_start + MAX_ROWS - 1)
    for r in range(data_start, last + 1):
        texts = [cell(vs, DB.SectionType.Body, r, c) for c in range(c0, c1 + 1)]
        nonblank = [t for t in texts if t.strip()]
        kind = "body"
        if not nonblank:
            kind = "blank"
        else:
            m = safe(lambda: body.GetMergedCell(r, c0))
            first = texts[0].strip()
            if m is not None and ncols > 1 and m.Left == c0 and m.Right >= c1 and m.Top <= r <= m.Bottom:
                kind = "group"
                group_label = first
            elif grand and r == r1:
                kind = "total"
            elif grand_title and first.startswith(grand_title):
                kind = "total"
            elif has_footer and group_label and first.startswith(group_label + ":"):
                # Group footer: Revit writes "<group>: <count>" (footer "Title and count").
                # A bare "<group>" is not used: an element can carry the same text (room "R2" on level R2).
                kind = "total"
            elif has_footer and ncols > 1 and first == "" and len(nonblank) < ncols and r > data_start \
                    and (r + 1 > r1 or not "".join(cell(vs, DB.SectionType.Body, r + 1, c) for c in range(c0, c1 + 1)).strip()):
                # Totals-only footer: first column blank and a blank spacer row follows.
                kind = "total"
        rows.append(texts)
        kinds.append(kind)

    out = {
        "name": vs.Name,
        "id": id_int(vs.Id),
        "category": category_name(vs),
        "kind": schedule_kind(vs),
        "title": title,
        "headerRows": header_rows,
        "headerSpans": header_spans,
        "columns": columns,
        "rows": rows,
        "rowKinds": kinds,
        "totalRows": total_rows,
        "truncated": total_rows > MAX_ROWS,
        "onSheet": id_int(vs.Id) in sheets,
        "sheets": sheets.get(id_int(vs.Id), []),
        "itemized": safe(lambda: d.IsItemized, None),
    }
    if out["truncated"]:
        out["note"] = "Showing the first %d of %d rows. Ask for a higher maxRows to read more." % (MAX_ROWS, total_rows)
    return out


def to_ascii_json(o):
    """JSON text with every non-ASCII character escaped as \\uXXXX.

    The agent runtime serializes `result` with IronPython's json module, which fails on
    non-ASCII text (for example a room named 'Cafe' with an accent). So the data goes out
    as one ASCII JSON string, `result["payload"]`, and render-table.ps1 unwraps it.
    """
    if o is None:
        return "null"
    if o is True:
        return "true"
    if o is False:
        return "false"
    if isinstance(o, (int, long, float)):  # noqa: F821  (IronPython 2.7 has long)
        return repr(o)
    if isinstance(o, basestring):  # noqa: F821
        parts = ['"']
        for ch in o:
            n = ord(ch)
            if ch == '"':
                parts.append('\\"')
            elif ch == '\\':
                parts.append('\\\\')
            elif n < 0x20 or n > 0x7e:
                parts.append('\\u%04x' % n)
            else:
                parts.append(ch)
        parts.append('"')
        return "".join(parts)
    if isinstance(o, dict):
        return "{" + ",".join(to_ascii_json(unicode(k)) + ":" + to_ascii_json(v) for k, v in o.items()) + "}"  # noqa: F821
    if isinstance(o, (list, tuple, set)):
        return "[" + ",".join(to_ascii_json(v) for v in o) + "]"
    return to_ascii_json(unicode(o))  # noqa: F821


def doc_info():
    return {
        "document": doc.Title,  # noqa: F821
        "revitVersion": "%s (%s)" % (app.VersionNumber, app.VersionBuild),  # noqa: F821
        "readAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


sheets = sheet_map()
info = doc_info()

if MODE == "read":
    found, missing = [], []
    scheds = all_schedules()
    by_name = dict((s.Name.strip().lower(), s) for s in scheds)
    by_id = dict((id_int(s.Id), s) for s in scheds)
    targets = []
    for n in WANT_NAMES:
        if n in by_name:
            targets.append(by_name[n])
        else:
            missing.append(n)
    for i in WANT_IDS:
        if i in by_id:
            targets.append(by_id[i])
        else:
            missing.append(str(i))
    seen = set()
    for vs in targets:
        if id_int(vs.Id) in seen:
            continue
        seen.add(id_int(vs.Id))
        if schedule_kind(vs) in ("revision", "keynote", "panel") and not INCLUDE_INTERNAL:
            missing.append(vs.Name + " (internal schedule; set includeInternal to read it)")
            continue
        found.append(read_one(vs, sheets))
    data = dict(info)
    data.update({"kind": "schedules", "rowKindSource": "heuristic", "schedules": found, "missing": missing})
else:
    items, skipped = [], {}
    for vs in all_schedules():
        k = schedule_kind(vs)
        if k in ("revision", "keynote", "panel") and not INCLUDE_INTERNAL:
            skipped[k] = skipped.get(k, 0) + 1
            continue
        n = safe(lambda: body_info(vs)[1].NumberOfRows, None)
        items.append({
            "name": vs.Name,
            "id": id_int(vs.Id),
            "category": category_name(vs),
            "kind": k,
            "rows": n,
            "onSheet": id_int(vs.Id) in sheets,
            "sheets": sheets.get(id_int(vs.Id), []),
        })
    items.sort(key=lambda s: s["name"].lower())
    data = dict(info)
    data.update({"kind": "schedule-list", "schedules": items, "skipped": skipped,
                 "note": "rows = body rows as Revit lays them out, including heading, group and total rows"})

# One ASCII JSON string (see to_ascii_json). Only ASCII-safe values sit beside it.
result = {
    "kind": data["kind"],
    "count": len(data["schedules"]),
    "missingCount": len(data.get("missing", [])),
    "payloadFormat": "ascii-json",
    "payload": to_ascii_json(data),
}

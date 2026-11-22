"""Compile single-sheet PDFs into one PDF set, in sheet-list order, with one bookmark per sheet.

Usage:
  python compile_set.py --check
  python compile_set.py <src_folder> <sheets.json> <out.pdf> [--dry] [--overwrite] [--report <report.json>]
         [--compress] [--no-title-block]
  python compile_set.py --plan <plan.json> <out.pdf> [--dry] [--overwrite] [--report <report.json>] [--compress]

--plan builds from the page plan of find_sources.py (many folders, pages inside combined PDFs).
The scan rules below then belong to find_sources.py; the build, overwrite, manifest and verify
rules stay the same.

<sheets.json> is the output of read_sheet_list.py: [{"sheet", "title", ...}] in list order.

Rules (fixed, so every package compiles the same way):
- Only sheets in <sheets.json> go in. PDFs for other sheet numbers are left out and listed.
- A PDF matches a sheet by the sheet number at the start of its file name. The separator after
  the number can be a space or a hyphen: "A-101 PLAN.pdf", "A-101-PLAN.pdf", "A-101 - PLAN.pdf".
- When two or more PDFs have the same sheet number, the script first reads the sheet number in
  each title block (needs pdfplumber). A file whose title block shows another listed sheet goes to
  that sheet (NUMBER FROM TITLE BLOCK, bookmark "<title block number> <title>"). A title block that
  cannot be read gives SAME NUMBER, CHECK. Then the newest file (modified time) wins.
- The bookmark is the PDF file name without ".pdf", with the separator made one space:
  "A-101 - PLAN.pdf" -> "A-101 PLAN".
- A listed sheet with no PDF is left out and listed as missing.
- Source PDFs are only read. They never change.
- --compress compresses page content and merges identical objects (fonts, title block images)
  before the write. It never changes what a page shows. The SIZE line shows the result.
- An existing output is never replaced without --overwrite. The new file is written to
  "<out>.partial" and then renamed, so a failed run leaves the old file whole.
- The PDF stores the page manifest (sheet, bookmark, file, mtime) in its metadata as
  /SheetManifest. With an existing output, the script compares it with the new plan and prints
  what changed.
Exit codes: 0 ok, 2 bad arguments, 3 pypdf missing, 4 output exists (no --overwrite),
5 output locked (open in another program), 6 a source PDF has more than one page,
7 verification failed.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

NAME_RE = re.compile(r"^([A-Z]{1,3}-?\d{2,4}(?:\.\d+)?[A-Z]?)\s*(?:-\s*|\s+)(.+?)\.pdf$", re.I)
HIDDEN_OR_SYSTEM = 0x2 | 0x4


def parse_name(filename):
    """Return (sheet_number_upper, title) or None. Pure logic, used by the tests."""
    m = NAME_RE.match(filename)
    if not m:
        return None
    return m.group(1).upper(), m.group(2).strip()


def normalize_title(title):
    """One naming rule for bookmarks: no leading '-', '_' or spaces, single spaces, upper case.
    Pure logic, used by the tests."""
    t = re.sub(r"^[\s_\-]+", "", title)
    t = re.sub(r"\s+", " ", t).strip()
    return t.upper()


def merge_sources(primary, fallbacks):
    """Pure logic: sheets found in the primary scan win; a fallback scan fills only sheet numbers
    the primary does not have. Each entry gets its folder index (0 = primary)."""
    merged = {}
    for idx, scan in enumerate([primary] + list(fallbacks)):
        for k, v in scan.items():
            if k not in merged:
                merged[k] = [(mt, n, t, idx) for (mt, n, t) in v]
    return merged


def scan_folder(src):
    """Map sheet number -> list of (mtime, filename, title), newest first. Also return names not parsed."""
    files, unparsed = {}, []
    for n in sorted(os.listdir(src)):
        p = os.path.join(src, n)
        if not os.path.isfile(p) or not n.lower().endswith(".pdf"):
            continue
        attrs = getattr(os.stat(p), "st_file_attributes", 0)
        if attrs & HIDDEN_OR_SYSTEM:
            continue
        parsed = parse_name(n)
        if not parsed:
            unparsed.append(n)
            continue
        files.setdefault(parsed[0], []).append((os.path.getmtime(p), n, parsed[1]))
    for v in files.values():
        v.sort(reverse=True)
    return files, unparsed


def stamp(t):
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def renumber_files(files, tb):
    """Pure logic. files: {sheet: [(mtime, name, title, folder)]}. tb: {(folder, name): listed sheet
    from the title block, or None when it could not be read}, only for checked files. A file whose
    title block shows another listed sheet moves there (5th item = the number in its name).
    Returns (files, moved [(name, from, to)], check [(sheet, [names])])."""
    out, moved, check = {}, [], []
    for k, cands in files.items():
        unknown = []
        for c in cands:
            folder = c[3] if len(c) > 3 else 0
            if (folder, c[1]) not in tb:
                out.setdefault(k, []).append(c)
                continue
            t = tb[(folder, c[1])]
            if t and t != k:
                out.setdefault(t, []).append((c[0], c[1], c[2], folder, k))
                moved.append((c[1], k, t))
                continue
            if not t:
                unknown.append(c[1])
            out.setdefault(k, []).append(c)
        if unknown:
            check.append((k, [c[1] for c in cands if ((c[3] if len(c) > 3 else 0), c[1]) in tb]))
    for v in out.values():
        v.sort(key=lambda c: -c[0])
    return out, moved, check


def check_same_number(files, listed, folders, reader=None):
    """Read the title block of every file of a listed sheet that has two or more files.
    reader(path, want) -> listed sheet or None. Returns renumber_files(...) and a note or None."""
    want = {}
    note = None
    if reader is None:
        try:
            import pdfplumber  # noqa: F401
            import find_sources as fs
        except ImportError:
            fs = None
            note = "pdfplumber missing: title blocks of files with one sheet number are not read"

        def reader(path, w):
            if fs is None:
                return None
            return fs.pick_title_block(fs.title_block_tokens((path, 0))[2], w)
    for k in listed:
        want[re.sub(r"[\s\-\.]", "", k).upper()] = k
    tb = {}
    for k in listed:
        cands = files.get(k, [])
        if len(cands) < 2:
            continue
        for c in cands:
            folder = c[3] if len(c) > 3 else 0
            tb[(folder, c[1])] = reader(os.path.join(folders[folder], c[1]), want)
    out, moved, check = renumber_files(files, tb)
    return out, moved, check, note


def build_plan(sheets, files):
    """Pure logic: return (plan, missing, duplicates, excluded)."""
    plan, missing, dups = [], [], []
    listed = set()
    for s in sheets:
        key = s["sheet"].strip().upper()
        if key in listed:
            continue
        listed.add(key)
        cands = files.get(key)
        if not cands:
            missing.append(s["sheet"] + " " + s.get("title", ""))
            continue
        mt, name, title = cands[0][:3]
        folder = cands[0][3] if len(cands[0]) > 3 else 0
        if len(cands) > 1:
            dups.append({"sheet": key, "used": name, "ignored": [c[1] for c in cands[1:]]})
        bookmark = key + " " + normalize_title(title)
        entry = {"sheet": key, "bookmark": bookmark, "file": name, "mtime": stamp(mt), "folder": folder}
        if bookmark != key + " " + title:
            entry["raw"] = key + " " + title
        if len(cands[0]) > 4 and cands[0][4]:
            entry["note"] = "file name says %s, title block says %s" % (cands[0][4], key)
        plan.append(entry)
    excluded = sorted(c[1] for k, v in files.items() if k not in listed for c in v)
    return plan, missing, dups, excluded


def diff_manifest(old, new):
    """Pure logic: compare two manifests. Return a list of human-readable change lines."""
    om = {o["sheet"]: o for o in old}
    nm = {n["sheet"]: n for n in new}
    lines = []
    for n in new:
        o = om.get(n["sheet"])
        if not o:
            lines.append("ADDED    %s  <- %s (%s)" % (n["sheet"], n["file"], n["mtime"]))
        elif o["file"] != n["file"] or o["mtime"] != n["mtime"]:
            lines.append("UPDATED  %s  %s (%s) -> %s (%s)" % (n["sheet"], o["file"], o["mtime"], n["file"], n["mtime"]))
        if o and o["bookmark"] != n["bookmark"]:
            lines.append("RENAMED  bookmark %r -> %r" % (o["bookmark"], n["bookmark"]))
    for o in old:
        if o["sheet"] not in nm:
            lines.append("REMOVED  %s  (%s)" % (o["sheet"], o["file"]))
    old_order = [o["sheet"] for o in old if o["sheet"] in nm]
    new_order = [n["sheet"] for n in new if n["sheet"] in om]
    if old_order != new_order:
        lines.append("ORDER    the page order changed")
    return lines


def long_path(p):
    """Windows paths over 260 characters need the \\\\?\\ prefix."""
    p = os.path.abspath(p)
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + p
    return p


def raise_pypdf_limits():
    """Some consultant PDFs have over-long number fields that pypdf refuses by default."""
    try:
        from pypdf.generic import NumberObject
        NumberObject._LENGTH_LIMIT = max(getattr(NumberObject, "_LENGTH_LIMIT", 0), 4096)
    except Exception:
        pass


def load_plan(path, drop):
    """Read a find_sources.py plan. Return (plan, missing, removed) in compile_set's shape."""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    plan, removed = [], []
    for p in d["plan"]:
        if p["sheet"].upper() in drop:
            removed.append(p["sheet"])
            continue
        plan.append({"sheet": p["sheet"], "bookmark": p["bookmark"], "file": os.path.basename(p["file"]),
                     "page": p.get("page", 0), "mtime": p["mtime"], "path": p["file"], "folder": 0})
    missing = [(m["sheet"] + " " + m.get("list_title", "")).strip() for m in d.get("missing", [])
               if m["sheet"].upper() not in drop]
    return plan, missing, removed


def compress_writer(w):
    """Lossless size step: compress each page's content stream, then write identical objects
    (fonts, images that repeat on every sheet) once."""
    for pg in w.pages:
        try:
            pg.compress_content_streams()
        except Exception:
            pass
    try:
        w.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    except Exception:
        pass


def read_manifest(path):
    from pypdf import PdfReader
    try:
        meta = PdfReader(path).metadata or {}
        return json.loads(meta.get("/SheetManifest", "[]"))
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?")
    ap.add_argument("sheets", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--report")
    ap.add_argument("--fallback", action="append", default=[],
                    help="extra source folder; used only for sheets the main folder does not have (repeat in priority order)")
    ap.add_argument("--plan", help="page plan from find_sources.py (replaces <src_folder> and <sheets.json>)")
    ap.add_argument("--exclude", action="append", default=[],
                    help="sheet number the user removed from this package, even if the list marks it (repeatable)")
    ap.add_argument("--compress", action="store_true", help="compress page content and merge identical objects")
    ap.add_argument("--no-title-block", action="store_true",
                    help="do not read title blocks of files that share one sheet number")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # file names can hold characters the Windows console code page lacks
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    t0 = time.time()
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        print("pypdf is missing. Install it with: python -m pip install --user pypdf")
        return 3
    if a.check:
        import pypdf
        print("pypdf", pypdf.__version__)
        return 0
    raise_pypdf_limits()
    drop = {x.strip().upper() for x in a.exclude}
    if a.plan:
        a.out = a.out or a.sheets or a.src
        if not a.out:
            ap.print_usage()
            return 2
        plan, missing, removed = load_plan(a.plan, drop)
        dups, excluded, unparsed, folders = [], [], [], [""]
        moved, check, tb_note = [], [], None
    else:
        if not (a.src and a.sheets and a.out):
            ap.print_usage()
            return 2
        with open(a.sheets, encoding="utf-8") as fh:
            sheets = json.load(fh)
        removed = [s["sheet"] for s in sheets if s["sheet"].strip().upper() in drop]
        sheets = [s for s in sheets if s["sheet"].strip().upper() not in drop]
        folders = [a.src] + a.fallback
        files, unparsed = scan_folder(a.src)
        fb_scans = []
        for f in a.fallback:
            fs, _ = scan_folder(f)
            fb_scans.append(fs)
        files = merge_sources(files, fb_scans)
        moved, check, tb_note = [], [], None
        if not a.no_title_block:
            listed = {s["sheet"].strip().upper() for s in sheets}
            files, moved, check, tb_note = check_same_number(files, listed, folders)
        plan, missing, dups, excluded = build_plan(sheets, files)
        excluded = [e for e in excluded if not any(e == c[1] for k in drop for c in files.get(k, []))]
    exists = os.path.exists(a.out)
    old = read_manifest(a.out) if exists else None
    changes = diff_manifest(old, plan) if old else []

    print("PAGES     %d" % len(plan))
    for s in removed:
        print("REMOVED BY USER  " + s)
    for p in plan:
        if p.get("folder"):
            print("FALLBACK  %s from %s: %s (%s)" % (p["sheet"], folders[p["folder"]], p["file"], p["mtime"]))
    for p in plan:
        if "raw" in p:
            print("NAME FIXED  %r -> %r" % (p["raw"], p["bookmark"]))
    if tb_note:
        print("NOTE      " + tb_note)
    for name, frm, to in moved:
        print("NUMBER FROM TITLE BLOCK  %s -> %s (file name says %s)" % (name, to, frm))
    for sh, names in check:
        print("SAME NUMBER, CHECK  %s: title block not read in %s; newest used" % (sh, ", ".join(names)))
    for m in missing:
        print("MISSING   " + m)
    for d in dups:
        print("NEWEST    %s uses %s; ignores %s" % (d["sheet"], d["used"], ", ".join(d["ignored"])))
    for e in excluded:
        print("NOT LISTED (left out)  " + e)
    for u in unparsed:
        print("NAME NOT READ (left out)  " + u)
    if exists:
        print("OUTPUT EXISTS  " + a.out + ("" if old is not None else "  (no manifest: not made by this script)"))
        for c in changes:
            print("CHANGE    " + c)
        if old is not None and not changes:
            print("CHANGE    none")
    report = {"pages": plan, "missing": missing, "duplicates": dups, "excluded": excluded,
              "unparsed": unparsed, "changes": changes, "output_exists": exists,
              "number_from_title_block": [{"file": n, "name_says": f, "sheet": t} for n, f, t in moved],
              "same_number_check": [{"sheet": sh, "files": n} for sh, n in check]}
    if a.report:
        with open(a.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, ensure_ascii=False)
    if a.dry:
        return 0
    if exists and not a.overwrite:
        print("STOP: the output exists. Ask the user, then run again with --overwrite or a new name.")
        return 4

    w = PdfWriter()
    readers = {}
    for i, it in enumerate(plan):
        path = it.get("path") or os.path.join(folders[it["folder"]], it["file"])
        if path not in readers:
            readers[path] = PdfReader(long_path(path))
        r = readers[path]
        if "path" not in it and len(r.pages) != 1:
            print("STOP: %s has %d pages. This script takes single-sheet PDFs only." % (it["file"], len(r.pages)))
            return 6
        w.add_page(r.pages[it.get("page", 0)])
        w.add_outline_item(title=it["bookmark"], page_number=i)
    if a.compress:
        compress_writer(w)
    w.page_mode = "/UseOutlines"
    manifest = [{k: v for k, v in p.items() if k != "path"} for p in plan]
    w.add_metadata({"/Title": os.path.splitext(os.path.basename(a.out))[0],
                    "/SheetManifest": json.dumps(manifest, ensure_ascii=False)})
    tmp = a.out + ".partial"
    with open(tmp, "wb") as fh:
        w.write(fh)
    try:
        os.replace(tmp, a.out)
    except PermissionError:
        os.remove(tmp)
        print("STOP: the output is locked. Close it in Bluebeam or Acrobat, then run again.")
        return 5

    r = PdfReader(a.out)
    bad = []
    outline = r.outline
    for i, (o, it) in enumerate(zip(outline, plan)):
        if o.title != it["bookmark"] or r.get_destination_page_number(o) != i:
            bad.append("%d %s" % (i + 1, o.title))
    ok = len(r.pages) == len(plan) == len(outline) and not bad
    print("VERIFY    pages %d, bookmarks %d, plan %d, %s" % (len(r.pages), len(outline), len(plan), "OK" if ok else "FAILED " + "; ".join(bad)))
    print("SIZE      %.1f MB%s" % (os.path.getsize(a.out) / 1e6, "  (compressed)" if a.compress else ""))
    print("TIME      %.1f s" % (time.time() - t0))
    return 0 if ok else 7


if __name__ == "__main__":
    sys.exit(main())

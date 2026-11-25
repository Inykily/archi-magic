"""Find the source page for every listed sheet across many folders, including pages inside
combined (multi-page) PDFs. Writes a page plan that compile_set.py --plan builds from.

Usage:
  python find_sources.py --check
  python find_sources.py <sheets.json> --folder <dir> [--folder <dir> ...] --plan <plan.json>
         [--prefer <dir> [--prefer-prefix A,G,T | --prefer-prefix *]] [--skip-dir NAME ...]
         [--skip-file TEXT ...] [--max-mb N] [--cache <file> | --no-cache]
         [--no-combined] [--no-text] [--workers N]

Rules (fixed, so every package is found the same way):
- Folders are scanned with all subfolders. Folder names that contain a --skip-dir word are left out
  (default: archive, superseded, superceded, combined, specification, __macosx).
- A file matches a sheet when its name holds the sheet number anywhere, for example
  "A-101 PLAN.pdf", "Firm_Project - Sheet - M-101 - PLAN.pdf", "FS1-0 PLAN.pdf" (for FS1.0),
  "P-900 PLAN.pdf" (for P-900.00), "TA-101M PLAN.pdf". Spaces, "-" and "." in numbers are ignored.
- A single-sheet PDF with no listed number in its name is matched only by its own bookmark.
- Two or more single-sheet PDFs with one sheet number in the name, in one folder or with different
  titles, are checked against their title blocks (needs pdfplumber). A title block that shows a
  different listed number moves the file to that number (NUMBER FROM TITLE BLOCK). A title block
  that cannot be read gives SAME NUMBER, CHECK. Title blocks that agree keep newest-wins.
- A multi-page PDF is a combined PDF. Each page gets a sheet from the PDF's own bookmarks. A
  bookmark sheet that points to more than one page is a group label and is not used. Pages with
  no bookmark sheet are read from the title block: the biggest listed sheet number in the
  bottom-right quarter of the page (needs pdfplumber). A page between two pages that are
  consecutive in the list gets the missing sheet by position.
- A page from a combined PDF loses to any other source of that sheet in the combined PDF's own
  folder or its subfolders: a combined PDF there was made from those files later, so its date is
  the date it was combined, not the date the sheet changed.
- Then the newest file (modified time) wins. With --prefer, a sheet takes the newest single-sheet
  PDF in the --prefer folder (or its subfolders) first, when that folder has one. --prefer-prefix
  limits this to some prefixes; "*" or no --prefer-prefix means every prefix.
- Bookmark: "<SHEET> <TITLE>", upper case, single spaces. The title is the text after the sheet
  number in the file name (single PDFs) or in the source bookmark (combined pages). With neither,
  the title from the drawing list is used and title_from says "drawing list".
- Page counts, bookmarks and title block words are cached in a JSON file (default: next to the
  plan), keyed by path, size and modified time. A second run on the same folders is fast.
- --max-mb N leaves out PDFs bigger than N MB without opening them (NOT READ (over N MB)).
Exit codes: 0 ok, 2 bad arguments, 3 pypdf missing.
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys

SKIP_DIRS = ("archive", "superseded", "superceded", "combined", "specification", "__macosx")
TOK = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,3})\s?-?\s?(\d{1,4})(?:[.\-](\d{1,2}))?([A-Z])?(?![0-9A-Za-z])", re.I)
TITLE_TOK = re.compile(r"^([A-Z]{1,3})-?(\d{1,4})(?:[.\-](\d{1,2}))?([A-Z])?$", re.I)
CACHE_NAME = "find_sources_cache.json"


def long_path(p):
    """Windows paths over 260 characters need the \\\\?\\ prefix."""
    p = os.path.abspath(p)
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + p
    return p


def norm(s):
    return re.sub(r"[\s\-\.]", "", s or "").upper()


def sheet_key(s):
    """The sheet number as it goes in the bookmark: list text without spaces, upper case."""
    return re.sub(r"\s+", "", s).upper()


def clean_title(t):
    t = re.sub(r"^[\s_\-]+", "", t or "")
    return re.sub(r"\s+", " ", t).strip().upper()


def find_sheet(text, want):
    """Return (listed sheet, title after the number) for the first listed sheet number in text.
    Pure logic, used by the tests."""
    for m in TOK.finditer(text):
        letters, digits, sub, suffix = m.group(1).upper(), m.group(2), m.group(3), (m.group(4) or "").upper()
        base = letters + digits
        options = []
        if sub:
            options.append(base + sub + suffix)
        options += [base + suffix, base] if suffix else [base]
        options.append(base + "00")
        for k in options:
            if k in want:
                return want[k], clean_title(text[m.end():])
    return None, None


class Cache(object):
    """Page counts, bookmarks and title block words per file, keyed by path, size and mtime."""

    def __init__(self, path=None):
        self.path, self.data, self.hits, self.misses, self.seen = path, {}, 0, 0, set()
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    self.data = json.load(fh)
            except Exception:
                self.data = {}

    @staticmethod
    def key(path):
        st = os.stat(long_path(path))
        return "%s|%d|%d" % (os.path.normcase(os.path.abspath(path)), st.st_size, int(st.st_mtime))

    def entry(self, path):
        return self.data.setdefault(self.key(path), {})

    def save(self):
        if not self.path:
            return
        live = {k: v for k, v in self.data.items() if v}
        tmp = self.path + ".partial"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(live, fh, ensure_ascii=False)
        os.replace(tmp, self.path)


def read_pdf(path, cache):
    """Return (page count, [[bookmark title, page index], ...]). -1 pages = not readable. Cached."""
    e = cache.entry(path)
    first = path not in cache.seen
    cache.seen.add(path)
    if "pages" in e:
        cache.hits += first
        return e["pages"], e.get("outline", [])
    cache.misses += 1
    from pypdf import PdfReader
    outline = []
    try:
        r = PdfReader(long_path(path))
        n = len(r.pages)
    except Exception:
        e["pages"] = -1
        return -1, []

    def walk(ol):
        for o in ol:
            if isinstance(o, list):
                walk(o)
                continue
            try:
                pg = r.get_destination_page_number(o)
            except Exception:
                continue
            if pg is not None:
                outline.append([getattr(o, "title", "") or "", pg])
    try:
        walk(r.outline)
    except Exception:
        pass
    e["pages"], e["outline"] = n, outline
    return n, outline


def match_outline(n, outline, want):
    """Pure logic: map page index -> (sheet, title) from bookmarks (group labels removed)."""
    got = {}
    for title, pg in outline:
        sh, t = find_sheet(title, want)
        if sh and 0 <= pg < n:
            got.setdefault(pg, (sh, t))
    count = collections.Counter(v[0] for v in got.values())
    return {k: v for k, v in got.items() if count[v[0]] == 1}


def title_block_tokens(args):
    """Words that look like a sheet number in the bottom-right quarter of one page, with their font
    size. Runs in a worker. Returns (path, index, [[text, size], ...]) or (path, index, None)."""
    path, index = args[0], args[1]
    try:
        import logging
        logging.disable(logging.CRITICAL)
        import pdfplumber
        with pdfplumber.open(long_path(path), pages=[index + 1]) as pdf:
            pg = pdf.pages[0]
            x0, top, x1, bottom = pg.bbox
            box = (x0 + (x1 - x0) * 0.6, top + (bottom - top) * 0.5, x1, bottom)
            words = pg.within_bbox(box).extract_words(extra_attrs=["size"])
    except Exception:
        return path, index, None
    out = []
    for w in words:
        t = w["text"].strip().strip(",;:()")
        if TITLE_TOK.match(t):
            out.append([t, float(w["size"])])
    return path, index, out


def pick_title_block(tokens, want):
    """Pure logic: the listed sheet number with the biggest font among the title block words."""
    best = None
    for t, size in tokens or []:
        sh, _ = find_sheet(t, want)
        if sh and (best is None or size > best[1]):
            best = (sh, size)
    return best[0] if best else None


def read_title_blocks(todo, cache, workers=0):
    """todo: [(path, page index)]. Returns {(path, index): tokens or None}. Uses the cache first.
    Raises ImportError when pdfplumber is missing and something must be read."""
    got, need = {}, []
    for path, i in todo:
        tb = cache.entry(path).get("tb", {})
        if str(i) in tb:
            got[(path, i)] = tb[str(i)]
        else:
            need.append((path, i))
    if not need:
        return got
    import pdfplumber  # noqa: F401
    if len(need) == 1 or workers == 1:
        results = map(title_block_tokens, need)
    else:
        from concurrent.futures import ProcessPoolExecutor
        ex = ProcessPoolExecutor(max_workers=workers or min(12, os.cpu_count() or 1))
        results = list(ex.map(title_block_tokens, need, chunksize=2))
        ex.shutdown()
    for path, i, toks in results:
        got[(path, i)] = toks
        if toks is not None:
            cache.entry(path).setdefault("tb", {})[str(i)] = toks
    return got


def fill_by_position(pages, order):
    """Pure logic. pages: {index: sheet or None}. A page with no sheet between two pages whose
    sheets are two apart in the list order gets the sheet in between. Returns {index: sheet}."""
    pos = {s: i for i, s in enumerate(order)}
    added = {}
    for i in sorted(pages):
        if pages[i]:
            continue
        a, b = pages.get(i - 1), pages.get(i + 1)
        if a in pos and b in pos and pos[b] - pos[a] == 2:
            added[i] = order[pos[a] + 1]
    return added


def scan(folders, want, skip_dirs, skip_files, cache=None, max_mb=0):
    """Return single-sheet candidates {sheet: [..]}, combined PDF paths, names not read, names with
    no number (bookmark only) and files over --max-mb."""
    cache = cache or Cache()
    single, combined, unread, bookmark_only, too_big = collections.defaultdict(list), [], [], [], []
    for root in folders:
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if not any(s in d.lower() for s in skip_dirs)]
            for f in fn:
                if not f.lower().endswith(".pdf") or any(s.lower() in f.lower() for s in skip_files):
                    continue
                full = os.path.join(dp, f)
                if max_mb and os.path.getsize(long_path(full)) > max_mb * 1e6:
                    too_big.append(full)
                    continue
                n, _ = read_pdf(full, cache)
                if n > 1:
                    combined.append(full)
                    continue
                if n != 1:
                    unread.append(full)
                    continue
                sh, title = find_sheet(f[:-4], want)
                if not sh:
                    bookmark_only.append(full)  # no number in the name: trust only its own bookmark
                    continue
                single[sh].append({"kind": "single", "file": full, "page": 0, "title": title,
                                   "mtime": os.path.getmtime(long_path(full)), "how": "file name"})
    return single, combined, unread, bookmark_only, too_big


def same_number_groups(single):
    """Pure logic: files to check by title block. A sheet number with two or more single PDFs in one
    folder, or with different titles, is checked; plain versions in other folders are not."""
    todo = []
    for sh, cands in single.items():
        if len(cands) < 2:
            continue
        dirs = collections.Counter(os.path.normcase(os.path.dirname(c["file"])) for c in cands)
        titles = {c.get("title") or "" for c in cands}
        if max(dirs.values()) > 1 or len(titles) > 1:
            todo += [c["file"] for c in cands]
    return todo


def renumber_by_title_block(single, tb):
    """Pure logic. single: {sheet: [cand]}. tb: {file: sheet from its title block, or None when it
    could not be read}, only for files that were checked. A file whose title block shows another
    listed sheet moves to that sheet. Returns (single, moved [(file, from, to)], check [(sheet, files)])."""
    out, moved, check = collections.defaultdict(list), [], []
    for sh, cands in single.items():
        unknown = []
        for c in cands:
            if c["file"] not in tb:
                out[sh].append(c)
                continue
            t = tb[c["file"]]
            if t and t != sh:
                out[t].append(dict(c, how="title block", name_sheet=sheet_key(sh),
                                   note="file name says %s, title block says %s" % (sheet_key(sh), sheet_key(t))))
                moved.append((c["file"], sheet_key(sh), sheet_key(t)))
                continue
            if not t:
                unknown.append(c["file"])
            out[sh].append(c)
        if unknown:
            check.append((sheet_key(sh), [c["file"] for c in cands if c["file"] in tb]))
    return out, moved, check


def inside(child_dir, parent_dir):
    c = os.path.normcase(os.path.abspath(child_dir))
    p = os.path.normcase(os.path.abspath(parent_dir))
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def drop_compiled(cands):
    """Pure logic: remove combined-PDF pages that have another source in their own folder tree."""
    keep = []
    for c in cands:
        if c["kind"] == "page":
            home = os.path.dirname(c["file"])
            if any(o["file"] != c["file"] and inside(os.path.dirname(o["file"]), home) for o in cands):
                continue
        keep.append(c)
    return keep


def parse_prefixes(text):
    """'A,G' -> {'A', 'G'}. '*' or '' -> None (every prefix)."""
    got = {p.strip().upper() for p in (text or "").split(",") if p.strip()}
    return None if not got or "*" in got else got


def prefix_of(sheet):
    m = re.match(r"[A-Za-z]+", sheet.strip())
    return m.group().upper() if m else ""


def choose(sheets, single, pages, prefer, prefer_prefix):
    """Pure logic: pick one source per listed sheet. prefer_prefix None = every prefix.
    Returns (plan, missing)."""
    plan, missing = [], []
    for s in sheets:
        sh = s["sheet"]
        everything = single.get(sh, []) + pages.get(sh, [])
        kept = drop_compiled(everything)
        # dropped compiled pages stay at the end, only for the "not used" list
        cands = sorted(kept, key=lambda c: -c["mtime"]) + sorted([c for c in everything if c not in kept], key=lambda c: -c["mtime"])
        if prefer and (prefer_prefix is None or prefix_of(sh) in prefer_prefix):
            first = [c for c in cands if c["kind"] == "single" and inside(os.path.dirname(c["file"]), prefer)]
            cands = first[:1] + [c for c in cands if c not in first[:1]]
        if not cands:
            missing.append({"sheet": sheet_key(sh), "list_title": (s.get("title") or "").strip(), "group": s.get("group", "")})
            continue
        pick = cands[0]
        title, frm = pick.get("title"), "file name" if pick["kind"] == "single" else "source bookmark"
        if not title:
            title, frm = clean_title(s.get("title", "")), "drawing list"
        entry = {"sheet": sheet_key(sh), "list_title": (s.get("title") or "").strip(), "group": s.get("group", ""),
                 "bookmark": (sheet_key(sh) + " " + title).strip(), "title_from": frm,
                 "kind": pick["kind"], "how": pick["how"], "file": pick["file"], "page": pick["page"],
                 "mtime": datetime.datetime.fromtimestamp(pick["mtime"]).strftime("%Y-%m-%d %H:%M"),
                 "not_used": [{"file": c["file"], "page": c["page"],
                               "mtime": datetime.datetime.fromtimestamp(c["mtime"]).strftime("%Y-%m-%d %H:%M")}
                              for c in cands[1:]]}
        if pick.get("note"):
            entry["note"] = pick["note"]
        plan.append(entry)
    return plan, missing


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("sheets", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--folder", action="append", default=[])
    ap.add_argument("--plan")
    ap.add_argument("--prefer")
    ap.add_argument("--prefer-prefix", default="", help="A,G,T or * (default with --prefer: every prefix)")
    ap.add_argument("--skip-dir", action="append", default=[])
    ap.add_argument("--skip-file", action="append", default=[])
    ap.add_argument("--max-mb", type=float, default=0, help="leave out PDFs bigger than this, unopened")
    ap.add_argument("--cache", help="cache file (default: %s next to the plan)" % CACHE_NAME)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-combined", action="store_true")
    ap.add_argument("--no-text", action="store_true")
    ap.add_argument("--workers", type=int, default=0)
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # file names can hold characters the Windows console code page lacks
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        import pypdf  # noqa: F401
    except ImportError:
        print("pypdf is missing. Install it with: python -m pip install --user pypdf")
        return 3
    if a.check:
        import pypdf
        print("pypdf", pypdf.__version__)
        try:
            import pdfplumber
            print("pdfplumber", pdfplumber.__version__)
        except ImportError:
            print("pdfplumber missing (optional: reads sheet numbers from title blocks)")
        return 0
    if not (a.sheets and a.folder and a.plan):
        ap.print_usage()
        return 2
    import logging
    logging.disable(logging.CRITICAL)
    with open(a.sheets, encoding="utf-8") as fh:
        sheets = json.load(fh)
    want = {norm(s["sheet"]): s["sheet"] for s in sheets}
    order = [s["sheet"] for s in sheets]
    skip_dirs = tuple(SKIP_DIRS) + tuple(x.lower() for x in a.skip_dir)
    cache = Cache(None if a.no_cache else (a.cache or os.path.join(os.path.dirname(os.path.abspath(a.plan)), CACHE_NAME)))
    single, combined, unread, bookmark_only, too_big = scan(a.folder, want, skip_dirs, a.skip_file, cache, a.max_mb)

    found, todo = {}, []
    if not a.no_combined:
        for path in combined + bookmark_only:
            n, outline = read_pdf(path, cache)
            bm = match_outline(n, outline, want)
            found[path] = {i: (bm[i] if i in bm else None) for i in range(n)}
            if path in combined:
                todo += [(path, i) for i in range(n) if i not in bm]
    same = same_number_groups(single)
    todo += [(f, 0) for f in same]
    tokens = {}
    if todo and not a.no_text:
        try:
            tokens = read_title_blocks(todo, cache, a.workers)
        except ImportError:
            print("NOTE      pdfplumber missing: pages with no bookmark and title blocks are not read")
    single, moved, check = renumber_by_title_block(
        single, {f: pick_title_block(tokens.get((f, 0)), want) for f in same})

    pages = collections.defaultdict(list)
    for path, pm in found.items():
        for i in pm:
            if pm[i] is None and path in combined:
                sh = pick_title_block(tokens.get((path, i)), want)
                if sh:
                    pm[i] = (sh, None, "title block")
        mt = os.path.getmtime(long_path(path))
        flat = {i: (v[0] if v else None) for i, v in pm.items()}
        for i, sh in (fill_by_position(flat, order).items() if path in combined else []):
            pm[i] = (sh, None, "position")
        for i, v in pm.items():
            if not v:
                continue
            how = v[2] if len(v) > 2 else "bookmark"
            pages[v[0]].append({"kind": "page", "file": path, "page": i, "title": v[1],
                                "mtime": mt, "how": how})

    prefixes = parse_prefixes(a.prefer_prefix)
    plan, missing = choose(sheets, single, pages, a.prefer, prefixes)
    used = collections.Counter((p["file"], p["page"]) for p in plan)
    twice = [k for k, v in used.items() if v > 1]
    try:
        cache.save()
    except OSError as e:
        print("NOTE      cache not saved: %s" % e)
    with open(a.plan, "w", encoding="utf-8") as fh:
        json.dump({"plan": plan, "missing": missing, "order": [sheet_key(s["sheet"]) for s in sheets],
                   "folders": a.folder, "unread": unread, "too_big": too_big, "prefer": a.prefer or "",
                   "prefer_prefix": sorted(prefixes) if prefixes is not None else ["*"]},
                  fh, indent=1, ensure_ascii=False)

    print("LISTED    %d" % len(sheets))
    print("FOUND     %d  (single PDFs %d, pages from combined PDFs %d)" % (
        len(plan), sum(p["kind"] == "single" for p in plan), sum(p["kind"] == "page" for p in plan)))
    by = collections.Counter((p["kind"], os.path.dirname(p["file"]) if p["kind"] == "single" else p["file"]) for p in plan)
    for (kind, where), n in sorted(by.items(), key=lambda x: -x[1]):
        print("SOURCE    %4d  %-6s %s" % (n, kind, where))
    for p in plan:
        if p["how"] in ("title block", "position") and p["kind"] == "page":
            print("READ BY %-11s %s  %s p%d" % (p["how"].upper(), p["sheet"], os.path.basename(p["file"]), p["page"] + 1))
    for f, frm, to in moved:
        print("NUMBER FROM TITLE BLOCK  %s -> %s (file name says %s)" % (os.path.basename(f), to, frm))
    for sh, files in check:
        print("SAME NUMBER, CHECK  %s: title block not read in %s; newest used" % (
            sh, ", ".join(os.path.basename(f) for f in files)))
    for m in missing:
        print("MISSING   %s %s" % (m["sheet"], m["list_title"]))
    for k in twice:
        print("PAGE USED TWICE  %s p%d" % (k[0], k[1] + 1))
    for u in unread:
        print("NOT READ  " + u)
    for u in too_big:
        print("NOT READ (over %g MB)  %s" % (a.max_mb, u))
    if cache.path:
        print("CACHE     %d files reused, %d read  (%s)" % (cache.hits, cache.misses, cache.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())

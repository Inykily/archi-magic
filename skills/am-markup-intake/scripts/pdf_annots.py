# -*- coding: utf-8 -*-
"""Extract markup annotations (Bluebeam, Acrobat, ...) from a PDF.

    python pdf_annots.py <file.pdf> [--json out.json] [--backend auto|pymupdf|pypdf]
    python pdf_annots.py --check        (exit 0: a PDF library is usable, 3: none)

Backends: PyMuPDF ("import pymupdf" or "import fitz") if importable, else pypdf.
If neither is importable, print a clear message and exit 3. The skill then
falls back to reading the pages visually.

Exit codes: 0 ok, 1 bad input (file missing, not a PDF, encrypted), 3 no PDF library.

Output (kind "pdf-annotations"), all text verbatim from the file:
  {"kind": "pdf-annotations", "file": <name>, "backend": "pypdf|pymupdf",
   "pageCount": N,
   "pages": [{"page": 1, "width": pt, "height": pt, "rotation": 0,
              "sheetCandidates": ["A101", ...]}],
   "annotations": [{"id", "page", "subtype", "markupType", "intent", "author",
                    "subject", "date", "text", "textSource", "color", "rect",
                    "rectPt", "inReplyTo"}]}

- page is 1-based.
- rect is [x0, y0, x1, y1] as fractions of the page as seen (0..1, origin top
  left, page rotation applied). This is the shared frame for every region in
  am-markup-intake records, so annotation and visual regions can be compared.
- rectPt is the raw /Rect in PDF points (origin bottom left, unrotated).
- id is the annotation /NM when present, else "p<page>-a<n>" (n counts the
  non-popup annotations on the page in file order).
- Popup and Widget (form field) annotations are skipped. Replies keep their
  own record with inReplyTo = the parent id.
- sheetCandidates are sheet-number-like words in the page text layer. They are
  hints only: confirm the sheet number from the title block visually.
Pure CPython 3.6+, ASCII source.
"""
import argparse
import io
import json
import os
import re
import sys

SKIP_SUBTYPES = ("Popup", "Widget", "Link")

SHEET_RE = re.compile(r"^[A-Z]{1,3}-?\d{2,4}(?:\.\d{1,2})?[A-Z]?$")


# ---------------------------------------------------------------- pure helpers
def classify(subtype, intent, border_style, has_callout_line):
    """Markup type in plain words, from /Subtype + /IT + /BE (Bluebeam style)."""
    st = subtype or ""
    it = intent or ""
    if st in ("Polygon", "PolyLine") and (it.endswith("Cloud") or border_style == "C"):
        return "cloud"
    if st in ("Square", "Circle") and border_style == "C":
        return "cloud"
    if st == "FreeText":
        if it == "FreeTextCallout" or has_callout_line:
            return "callout"
        if it == "FreeTextTypeWriter":
            return "typewriter text"
        return "text box"
    return {
        "StrikeOut": "strike-out",
        "Underline": "underline",
        "Highlight": "highlight",
        "Squiggly": "squiggly underline",
        "Text": "note",
        "Ink": "pen (freehand)",
        "Line": "line" if it != "LineArrow" else "arrow",
        "Square": "rectangle",
        "Circle": "ellipse",
        "Polygon": "polygon",
        "PolyLine": "polyline",
        "Stamp": "stamp",
        "Caret": "insert mark",
        "FileAttachment": "attachment",
        "Sound": "sound",
        "Redact": "redaction",
    }.get(st, st.lower() or "unknown")


_DATE_RE = re.compile(r"^D?:?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
                      r"(?:([Zz+\-])(\d{2})?'?(\d{2})?'?)?")


def iso_date(raw):
    """PDF date 'D:20261015093000-04'00'' -> '2026-10-15T09:30:00-04:00'. '' if none."""
    if not raw:
        return ""
    m = _DATE_RE.match(str(raw).strip())
    if not m:
        return str(raw)
    y, mo, d, h, mi, s, sign, tzh, tzm = m.groups()
    out = "%s-%s-%sT%s:%s:%s" % (y, mo or "01", d or "01", h or "00", mi or "00", s or "00")
    if sign in ("Z", "z"):
        out += "Z"
    elif sign:
        out += "%s%s:%s" % (sign, tzh or "00", tzm or "00")
    return out


def color_hex(vals):
    """/C array (0..1 floats, gray / RGB / CMYK) -> '#rrggbb'. '' if none."""
    if not vals:
        return ""
    v = [float(x) for x in vals]
    if len(v) == 1:
        r = g = b = v[0]
    elif len(v) == 3:
        r, g, b = v
    elif len(v) == 4:
        c, m, y, k = v
        r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
    else:
        return ""
    return "#%02x%02x%02x" % tuple(int(round(max(0.0, min(1.0, x)) * 255)) for x in (r, g, b))


def strip_rich_text(rc):
    """/RC XHTML -> plain text. Keeps the words; drops tags and entities."""
    if not rc:
        return ""
    s = re.sub(r"<\?xml[^>]*\?>", "", str(rc))
    s = re.sub(r"<\s*(br|/p|/div)\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"),
                 ("&#39;", "'"), ("&nbsp;", " "), ("&amp;", "&")):
        s = s.replace(a, b)
    lines = [ln.strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def norm_rect(rect_pt, box, rotation):
    """PDF /Rect (points, bottom-left origin) -> fractions of the visible page.

    box = (x0, y0, x1, y1) MediaBox/CropBox. rotation = /Rotate (0/90/180/270,
    clockwise). Result origin is top left of the page as displayed.
    """
    bx0, by0, bx1, by1 = [float(v) for v in box]
    w, h = bx1 - bx0, by1 - by0
    x0, y0, x1, y1 = [float(v) for v in rect_pt]
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    # unrotated, top-left origin fractions
    u0, u1 = (x0 - bx0) / w, (x1 - bx0) / w
    v0, v1 = (by1 - y1) / h, (by1 - y0) / h
    rot = int(rotation or 0) % 360
    if rot == 90:
        u0, v0, u1, v1 = 1 - v1, u0, 1 - v0, u1
    elif rot == 180:
        u0, v0, u1, v1 = 1 - u1, 1 - v1, 1 - u0, 1 - v0
    elif rot == 270:
        u0, v0, u1, v1 = v0, 1 - u1, v1, 1 - u0
    return [round(max(0.0, min(1.0, t)), 4) for t in (u0, v0, u1, v1)]


def sheet_candidates(text):
    seen = []
    for word in re.split(r"[\s,;:()\[\]]+", text or ""):
        w = word.strip(".").upper()
        if SHEET_RE.match(w) and w not in seen:
            seen.append(w)
    return seen


def make_record(page_no, idx, nm, subtype, intent, be_style, has_cl, author, subject,
                date_raw, contents, rc, color, rect_pt, box, rotation, irt):
    text = (contents or "").strip()
    source = "contents"
    if not text and rc:
        text = strip_rich_text(rc)
        source = "rich text"
    if not text:
        source = "none"
    return {
        "id": nm or ("p%d-a%d" % (page_no, idx)),
        "page": page_no,
        "subtype": subtype,
        "markupType": classify(subtype, intent, be_style, has_cl),
        "intent": intent or "",
        "author": author or "",
        "subject": subject or "",
        "date": iso_date(date_raw),
        "text": text,
        "textSource": source,
        "color": color_hex(color),
        "rect": norm_rect(rect_pt, box, rotation),
        "rectPt": [round(float(v), 2) for v in rect_pt],
        "inReplyTo": irt or "",
    }


# ---------------------------------------------------------------- pypdf backend
def _pypdf_extract(path):
    import pypdf
    reader = pypdf.PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("the PDF is encrypted (password protected)")
    pages, annots = [], []

    def name_of(v):
        return str(v)[1:] if v is not None and str(v).startswith("/") else (str(v) if v is not None else "")

    for pno, page in enumerate(reader.pages, 1):
        box = [float(v) for v in page.cropbox]
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append({"page": pno, "width": round(box[2] - box[0], 2),
                      "height": round(box[3] - box[1], 2), "rotation": rotation,
                      "sheetCandidates": sheet_candidates(text)})
        raw = page.get("/Annots")
        if raw is None:
            continue
        raw = raw.get_object()
        objs = []
        for ref in raw:
            a = ref.get_object()
            st = name_of(a.get("/Subtype"))
            if st in SKIP_SUBTYPES:
                continue
            objs.append((ref, a, st))
        ids = {}
        for n, (ref, a, st) in enumerate(objs, 1):
            nm = a.get("/NM")
            ids[getattr(ref, "idnum", id(a))] = str(nm) if nm else "p%d-a%d" % (pno, n)
        for n, (ref, a, st) in enumerate(objs, 1):
            be = a.get("/BE")
            be_style = name_of(be.get_object().get("/S")) if be is not None else ""
            irt = a.get("/IRT")
            irt_id = ""
            if irt is not None:
                key = getattr(irt, "idnum", None)
                irt_id = ids.get(key, "")
                if not irt_id:
                    nm2 = irt.get_object().get("/NM")
                    irt_id = str(nm2) if nm2 else ""
            nm = a.get("/NM")
            color = a.get("/C")
            annots.append(make_record(
                pno, n, str(nm) if nm else "", st, name_of(a.get("/IT")), be_style,
                a.get("/CL") is not None, a.get("/T"), a.get("/Subj"),
                a.get("/M") or a.get("/CreationDate"), a.get("/Contents"), a.get("/RC"),
                [float(c) for c in color] if color else [],
                [float(v) for v in a.get("/Rect")], box, rotation, irt_id))
    return {"backend": "pypdf", "pageCount": len(reader.pages), "pages": pages, "annotations": annots}


# ---------------------------------------------------------------- PyMuPDF backend
def _pymupdf_extract(path):
    try:
        import pymupdf as fz
    except ImportError:
        import fitz as fz
    doc = fz.open(path)
    if doc.needs_pass:
        raise ValueError("the PDF is encrypted (password protected)")
    pages, annots = [], []

    def key(xref, k):
        t, v = doc.xref_get_key(xref, k)
        if t == "null":
            return None, None
        return t, v

    def pdf_str(xref, k):
        t, v = key(xref, k)
        if t is None:
            return ""
        return v if t == "string" else v.lstrip("/")

    def nums(xref, k):
        t, v = key(xref, k)
        if t != "array":
            return []
        return [float(x) for x in v.strip("[]").split()]

    for pno in range(doc.page_count):
        page = doc[pno]
        # Raw box values in PDF points (bottom-left origin), same as pypdf reads.
        box = nums(page.xref, "CropBox") or nums(page.xref, "MediaBox")
        if len(box) != 4:  # inherited from the page tree
            mb = page.mediabox
            box = [mb.x0, mb.y0, mb.x1, mb.y1]
        rotation = page.rotation % 360
        pages.append({"page": pno + 1, "width": round(box[2] - box[0], 2),
                      "height": round(box[3] - box[1], 2), "rotation": rotation,
                      "sheetCandidates": sheet_candidates(page.get_text())})
        t, arr = key(page.xref, "Annots")
        xrefs = []
        if t == "array":
            xrefs = [int(x) for x in re.findall(r"(\d+)\s+0\s+R", arr)]
        elif t == "xref":  # /Annots is an indirect array
            xrefs = [int(x) for x in re.findall(r"(\d+)\s+0\s+R", doc.xref_object(int(arr.split()[0])))]
        objs = []
        for x in xrefs:
            st = pdf_str(x, "Subtype")
            if st in SKIP_SUBTYPES:
                continue
            objs.append((x, st))
        ids = {}
        for n, (x, st) in enumerate(objs, 1):
            ids[x] = pdf_str(x, "NM") or "p%d-a%d" % (pno + 1, n)
        for n, (x, st) in enumerate(objs, 1):
            tbe, vbe = key(x, "BE/S")
            irt_id = ""
            ti, vi = key(x, "IRT")
            if ti == "xref":
                ix = int(vi.split()[0])
                irt_id = ids.get(ix) or pdf_str(ix, "NM")
            annots.append(make_record(
                pno + 1, n, pdf_str(x, "NM"), st, pdf_str(x, "IT"),
                (vbe or "").lstrip("/"), key(x, "CL")[0] is not None,
                pdf_str(x, "T"), pdf_str(x, "Subj"),
                pdf_str(x, "M") or pdf_str(x, "CreationDate"),
                pdf_str(x, "Contents"), pdf_str(x, "RC"), nums(x, "C"),
                nums(x, "Rect"), box, rotation, irt_id))
    out = {"backend": "pymupdf", "pageCount": doc.page_count, "pages": pages, "annotations": annots}
    doc.close()
    return out


def have(module):
    try:
        __import__(module)
        return True
    except Exception:
        return False


def pick_backend(wanted="auto"):
    fitz_ok = have("pymupdf") or have("fitz")
    if wanted == "pymupdf":
        return "pymupdf" if fitz_ok else None
    if wanted == "pypdf":
        return "pypdf" if have("pypdf") else None
    if fitz_ok:
        return "pymupdf"
    if have("pypdf"):
        return "pypdf"
    return None


def extract(path, backend="auto"):
    b = pick_backend(backend)
    if b is None:
        return None
    data = _pymupdf_extract(path) if b == "pymupdf" else _pypdf_extract(path)
    out = {"kind": "pdf-annotations", "file": os.path.basename(path)}
    out.update(data)
    return out


NO_LIB = ("NO-PDF-LIBRARY: neither PyMuPDF nor pypdf is installed for this Python.\n"
          "The annotation layer cannot be read. Read the pages visually instead.\n"
          "To add it (no admin rights needed): python -m pip install --user pymupdf")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract PDF markup annotations.")
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--json", dest="out", help="write the result to this file")
    ap.add_argument("--backend", default="auto", choices=["auto", "pymupdf", "pypdf"])
    ap.add_argument("--check", action="store_true",
                    help="only report the PDF library: exit 0 if one is usable, 3 if none")
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    if a.check:
        b = pick_backend(a.backend)
        if b is None:
            print(NO_LIB)
            return 3
        print("OK: PDF library: %s (Python %s)" % (b, sys.version.split()[0]))
        return 0
    if not a.pdf:
        ap.print_usage()
        print("FAIL: give a PDF file, or --check")
        return 1
    if not os.path.isfile(a.pdf):
        print("FAIL: file not found: %s" % a.pdf)
        return 1
    with open(a.pdf, "rb") as fh:
        if not fh.read(1024).lstrip().startswith(b"%PDF"):
            print("FAIL: not a PDF file: %s" % a.pdf)
            return 1
    if pick_backend(a.backend) is None:
        print(NO_LIB)
        return 3
    try:
        res = extract(a.pdf, a.backend)
    except ValueError as e:
        print("FAIL: %s" % e)
        return 1
    text = json.dumps(res, indent=1, ensure_ascii=True)
    if a.out:
        with io.open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    by_type = {}
    for r in res["annotations"]:
        by_type[r["markupType"]] = by_type.get(r["markupType"], 0) + 1
    summary = ", ".join("%s %d" % (k, v) for k, v in sorted(by_type.items())) or "none"
    print("OK: %s: %d page(s), %d annotation(s) [%s] backend=%s%s" % (
        res["file"], res["pageCount"], len(res["annotations"]), summary, res["backend"],
        (" -> " + a.out) if a.out else ""))
    if not a.out:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

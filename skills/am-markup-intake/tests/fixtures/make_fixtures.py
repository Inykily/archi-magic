# -*- coding: utf-8 -*-
"""Rebuild the synthetic markup set in this folder. No real project data.

    python make_fixtures.py

Needs pypdf and Pillow (only to rebuild; the tests read the committed files).
Writes:
  review-set.pdf   2 vector pages (sheets A101, A102 of the Snowdon Towers sample)
                   with real PDF annotations, Bluebeam style:
                   cloud (Polygon /IT /PolygonCloud), callout (FreeText
                   /IT /FreeTextCallout), text box (FreeText, text only in /RC),
                   strike-out, a sticky-note reply (/IRT), a Popup (must be skipped),
                   and one red redline drawn into the page content (no annotation).
  photo-a102.png   a "phone photo" of the printed A102 sheet with handwriting.
"""
import os

from pypdf import PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                           FloatObject, NameObject, NumberObject, TextStringObject)

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1224.0, 792.0  # tabloid landscape, points


def esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class Ink(object):
    def __init__(self):
        self.ops = []

    def line(self, x0, y0, x1, y1):
        self.ops.append("%g %g m %g %g l S" % (x0, y0, x1, y1))

    def rect(self, x, y, w, h):
        self.ops.append("%g %g %g %g re S" % (x, y, w, h))

    def text(self, x, y, s, size=10, font="F1"):
        self.ops.append("BT /%s %g Tf %g %g Td (%s) Tj ET" % (font, size, x, y, esc(s)))

    def color(self, r, g, b):
        self.ops.append("%g %g %g RG %g %g %g rg" % (r, g, b, r, g, b))

    def width(self, w):
        self.ops.append("%g w" % w)

    def bubble(self, x, y, label):
        # grid bubble: a square-ish circle made of 4 Bezier arcs
        r, k = 12.0, 12.0 * 0.5523
        self.ops.append("%g %g m %g %g %g %g %g %g c %g %g %g %g %g %g c "
                        "%g %g %g %g %g %g c %g %g %g %g %g %g c S" % (
                            x + r, y, x + r, y + k, x + k, y + r, x, y + r,
                            x - k, y + r, x - r, y + k, x - r, y,
                            x - r, y - k, x - k, y - r, x, y - r,
                            x + k, y - r, x + r, y - k, x + r, y))
        self.text(x - 3.5, y - 3.5, label, 10)

    def scallops(self, x0, y0, x1, y1, step=18.0):
        """A hand-drawn revision cloud: arcs along each edge of a box."""
        pts = []
        n = max(2, int((x1 - x0) / step))
        m = max(2, int((y1 - y0) / step))
        for i in range(n):
            pts.append((x0 + (x1 - x0) * i / n, y0, 0, -1))
        for i in range(m):
            pts.append((x1, y0 + (y1 - y0) * i / m, 1, 0))
        for i in range(n):
            pts.append((x1 - (x1 - x0) * i / n, y1, 0, 1))
        for i in range(m):
            pts.append((x0, y1 - (y1 - y0) * i / m, -1, 0))
        pts.append(pts[0])
        seg = ["%g %g m" % (pts[0][0], pts[0][1])]
        for a, b in zip(pts, pts[1:]):
            mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
            bx, by = mx + a[2] * 7, my + a[3] * 7
            seg.append("%g %g %g %g %g %g c" % (bx, by, bx, by, b[0], b[1]))
        self.ops.append(" ".join(seg) + " S")

    def data(self):
        return ("\n".join(self.ops)).encode("latin-1")


def title_block(ink, sheet, title):
    ink.color(0, 0, 0)
    ink.width(1.5)
    ink.rect(20, 20, W - 40, H - 40)
    ink.rect(1060, 20, 144, H - 40)
    ink.width(0.5)
    ink.text(1068, 740, "SNOWDON TOWERS", 9, "F2")
    ink.text(1068, 728, "SAMPLE - TEST FIXTURE", 7)
    ink.text(1068, 700, "NOT FOR CONSTRUCTION", 7)
    ink.line(1060, 120, 1204, 120)
    ink.text(1068, 100, title.upper(), 9, "F2")
    ink.text(1068, 80, "SHEET", 7)
    ink.text(1068, 40, sheet, 30, "F2")


def grids(ink):
    ink.color(0.3, 0.3, 0.3)
    ink.width(0.4)
    for i, x in enumerate([150, 350, 550, 750, 950]):
        ink.line(x, 120, x, 660)
        ink.bubble(x, 675, str(i + 1))
    for lab, y in [("A", 600), ("B", 400), ("C", 200)]:
        ink.line(100, y, 1000, y)
        ink.bubble(85, y, lab)


def page_a101():
    ink = Ink()
    title_block(ink, "A101", "First Floor Plan")
    grids(ink)
    ink.color(0, 0, 0)
    ink.width(1.2)
    ink.rect(160, 410, 180, 180)
    ink.text(200, 500, "105", 10, "F2")
    ink.text(200, 488, "COMMERCIAL/RETAIL", 8)
    ink.rect(360, 410, 180, 180)
    ink.text(400, 500, "106", 10, "F2")
    ink.text(400, 488, "RESIDENTIAL LOBBY", 8)
    ink.rect(150, 360, 800, 40)
    ink.text(520, 376, "CORRIDOR", 8)
    ink.rect(318, 404, 24, 12)  # door 105A
    ink.text(322, 420, "105A", 7)
    ink.rect(820, 440, 220, 150)
    ink.text(830, 574, "GENERAL NOTES", 9, "F2")
    ink.text(830, 556, "1. VERIFY ALL DIMENSIONS IN FIELD.", 7)
    ink.text(830, 544, "2. SEE A601 FOR DOOR SCHEDULE.", 7)
    ink.text(830, 532, "3. ALIGN FINISH FACES U.N.O.", 7)
    ink.text(830, 520, "4. ALL DIMENSIONS TO FACE OF STUD.", 7)
    # drawn redline, NOT an annotation: a red cloud + red text in the page content
    ink.color(0.85, 0.05, 0.05)
    ink.width(1.4)
    ink.scallops(470, 420, 535, 470)
    ink.line(535, 450, 600, 470)
    ink.text(604, 474, "ADD FE CABINET", 10, "F2")
    ink.text(604, 461, "SEE 7/A503", 9, "F2")
    return ink.data()


def page_a102():
    ink = Ink()
    title_block(ink, "A102", "Second Floor Plan")
    grids(ink)
    ink.color(0, 0, 0)
    ink.width(1.2)
    ink.rect(160, 410, 180, 180)
    ink.text(200, 500, "202", 10, "F2")
    ink.text(200, 488, "LIVE/WORK UNIT", 8)
    ink.rect(560, 410, 180, 180)
    ink.text(600, 500, "205", 10, "F2")
    ink.text(600, 488, "LIVE/WORK UNIT", 8)
    ink.rect(150, 360, 800, 40)
    ink.text(520, 376, "CORRIDOR", 8)
    ink.rect(570, 404, 24, 12)  # door 205A
    ink.text(574, 420, "205A", 7)
    return ink.data()


def name(s):
    return NameObject(s)


def txt(s):
    return TextStringObject(s)


def num_array(vals):
    return ArrayObject([FloatObject(v) for v in vals])


RED = [1, 0, 0]
BLUE = [0, 0, 1]
DATE = "D:20261015093000-04'00'"


def base(subtype, nm, author, subject, rect, color, contents=None):
    d = DictionaryObject()
    d[name("/Type")] = name("/Annot")
    d[name("/Subtype")] = name(subtype)
    d[name("/NM")] = txt(nm)
    d[name("/T")] = txt(author)
    d[name("/Subj")] = txt(subject)
    d[name("/M")] = txt(DATE)
    d[name("/CreationDate")] = txt(DATE)
    d[name("/Rect")] = num_array(rect)
    d[name("/C")] = num_array(color)
    d[name("/F")] = NumberObject(4)
    if contents is not None:
        d[name("/Contents")] = txt(contents)
    return d


def cloud(nm, author, rect, contents):
    d = base("/Polygon", nm, author, "Cloud+", rect, RED, contents)
    x0, y0, x1, y1 = rect
    d[name("/Vertices")] = num_array([x0 + 4, y0 + 4, x1 - 4, y0 + 4, x1 - 4, y1 - 4, x0 + 4, y1 - 4])
    d[name("/IT")] = name("/PolygonCloud")
    be = DictionaryObject()
    be[name("/S")] = name("/C")
    be[name("/I")] = NumberObject(1)
    d[name("/BE")] = be
    return d


def freetext(nm, author, subject, rect, contents, callout_to=None, rc=None):
    d = base("/FreeText", nm, author, subject, rect, BLUE, contents)
    d[name("/DA")] = txt("0 0 1 rg /Helv 10 Tf")
    if callout_to:
        d[name("/IT")] = name("/FreeTextCallout")
        d[name("/CL")] = num_array(callout_to)
    if rc:
        d[name("/RC")] = txt(rc)
    return d


def add_page(writer, content, annots, links=None):
    page = writer.add_blank_page(width=W, height=H)
    fonts = DictionaryObject()
    for key, base_font in [("/F1", "/Helvetica"), ("/F2", "/Helvetica-Bold")]:
        f = DictionaryObject()
        f[name("/Type")] = name("/Font")
        f[name("/Subtype")] = name("/Type1")
        f[name("/BaseFont")] = name(base_font)
        fonts[name(key)] = f
    res = DictionaryObject()
    res[name("/Font")] = fonts
    page[name("/Resources")] = res
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[name("/Contents")] = writer._add_object(stream)
    refs = []
    for a in annots:
        a[name("/P")] = page.indirect_reference
        refs.append(writer._add_object(a))
    # wire parents / popups / replies after the objects exist
    by_nm = dict((str(a.get("/NM", "")), (a, r)) for a, r in zip(annots, refs))
    for a, r in zip(annots, refs):
        link = (links or {}).get(str(a.get("/NM", "")))
        if link is None:
            continue
        kind, target = link
        if kind == "irt":
            a[name("/IRT")] = by_nm[target][1]
            a[name("/RT")] = name("/R")
        elif kind == "popup":
            a[name("/Parent")] = by_nm[target][1]
            by_nm[target][0][name("/Popup")] = r
    page[name("/Annots")] = ArrayObject(refs)
    return page


def build_pdf(path):
    w = PdfWriter()
    p1 = [
        cloud("fx-a1", "J. Rivera", [300, 392, 360, 432], "Revise door 105A swing to open out."),
        freetext("fx-a2", "J. Rivera", "Callout", [600, 300, 760, 340],
                 "Widen corridor to 6'-0\" clear.", callout_to=[560, 380, 590, 335, 600, 320]),
        freetext("fx-a3", "M. Chen", "Text Box", [600, 230, 800, 270], None,
                 rc="<?xml version=\"1.0\"?><body xmlns=\"http://www.w3.org/1999/xhtml\">"
                    "<p>Keep corridor at 5'-0\" clear per lease plan.</p></body>"),
        base("/StrikeOut", "fx-a4", "M. Chen", "Strikethrough", [828, 516, 980, 528], RED,
             "Delete note 4. Covered by spec."),
        base("/Text", "fx-a5", "M. Chen", "Note", [364, 420, 384, 440], [1, 1, 0],
             "Agreed. Check the hardware set too."),
        base("/Popup", "fx-a1-popup", "J. Rivera", "Popup", [400, 600, 600, 700], RED),
        freetext("fx-a6", "J. Rivera", "Text Box", [140, 690, 330, 720],
                 "Add dimension string to grid 3."),
    ]
    p1[3][name("/QuadPoints")] = num_array([828, 528, 980, 528, 828, 516, 980, 516])
    links = {"fx-a5": ("irt", "fx-a1"), "fx-a1-popup": ("popup", "fx-a1")}
    add_page(w, page_a101(), p1, links)
    p2 = [
        freetext("fx-b1", "J. Rivera", "Text Box", [150, 610, 420, 650],
                 "Confirm room name for 202: Live/Work Unit or Studio Unit?"),
        cloud("fx-b2", "J. Rivera", [552, 392, 612, 432], "Verify door swing at Room 205."),
        freetext("fx-b3", "J. Rivera", "Text Box", [140, 690, 330, 720],
                 "Add dimension string to grid 3."),
    ]
    add_page(w, page_a102(), p2)
    w.add_metadata({"/Title": "Synthetic review set (test fixture)", "/Author": "archi-magic tests"})
    with open(path, "wb") as fh:
        w.write(fh)


def build_png(path):
    from PIL import Image, ImageDraw, ImageFont
    fonts = "C:\\Windows\\Fonts"
    hand = ImageFont.truetype(os.path.join(fonts, "Inkfree.ttf"), 34)
    hand_small = ImageFont.truetype(os.path.join(fonts, "Inkfree.ttf"), 26)
    arial = ImageFont.truetype(os.path.join(fonts, "arialbd.ttf"), 46)
    arial_s = ImageFont.truetype(os.path.join(fonts, "arial.ttf"), 16)
    sheet = Image.new("RGB", (1100, 760), (246, 244, 236))
    d = ImageDraw.Draw(sheet)
    d.rectangle([10, 10, 1090, 750], outline=(30, 30, 30), width=3)
    d.rectangle([950, 10, 1090, 750], outline=(30, 30, 30), width=2)
    d.text((960, 600), "SECOND FLOOR", font=arial_s, fill=(20, 20, 20))
    d.text((960, 620), "PLAN", font=arial_s, fill=(20, 20, 20))
    d.text((960, 680), "A102", font=arial, fill=(20, 20, 20))
    for x in [120, 300, 480, 660, 840]:
        d.line([x, 60, x, 640], fill=(120, 120, 120), width=1)
    d.rectangle([140, 160, 300, 320], outline=(0, 0, 0), width=3)
    d.text((180, 220), "202", font=arial_s, fill=(0, 0, 0))
    d.rectangle([500, 160, 660, 320], outline=(0, 0, 0), width=3)
    d.text((540, 220), "205", font=arial_s, fill=(0, 0, 0))
    d.rectangle([510, 320, 534, 332], outline=(0, 0, 0), width=2)
    d.text((512, 336), "205A", font=arial_s, fill=(0, 0, 0))
    d.rectangle([110, 340, 900, 380], outline=(0, 0, 0), width=2)
    red = (200, 20, 30)
    d.ellipse([480, 300, 570, 360], outline=red, width=4)
    d.line([570, 340, 690, 430], fill=red, width=4)
    d.text((600, 435), "Verify door swing", font=hand, fill=red)
    d.text((600, 475), "at Rm 205", font=hand, fill=red)
    d.text((640, 210), "FYI - owner OK w/ carpet", font=hand_small, fill=(40, 60, 170))
    photo = Image.new("RGB", (1240, 900), (92, 84, 74))
    rot = sheet.rotate(-3.0, expand=True, fillcolor=(92, 84, 74), resample=Image.BICUBIC)
    photo.paste(rot, (40, 40))
    photo.save(path, optimize=True)


if __name__ == "__main__":
    build_pdf(os.path.join(HERE, "review-set.pdf"))
    build_png(os.path.join(HERE, "photo-a102.png"))
    print("wrote review-set.pdf and photo-a102.png in " + HERE)

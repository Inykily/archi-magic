# -*- coding: utf-8 -*-
"""Tests for pdf_annots.py and consolidate.py on the synthetic fixture set.

Run either way:
    python skills/am-markup-intake/tests/test_markup_intake.py
    python -m pytest skills/am-markup-intake/tests -q
Mutation check (each mutation must turn the suite RED):
    python skills/am-markup-intake/tests/mutate.py
"""
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, SCRIPTS)

import consolidate as C  # noqa: E402
import pdf_annots as P  # noqa: E402

PDF = os.path.join(FIX, "review-set.pdf")
VISUAL = os.path.join(FIX, "visual-records.json")
MODEL = os.path.join(FIX, "snowdon-model-index.json")

CHECKS = [0]


def check(cond, msg):
    CHECKS[0] += 1
    assert cond, msg


def eq(got, want, msg):
    CHECKS[0] += 1
    assert got == want, "%s\n  got:  %r\n  want: %r" % (msg, got, want)


# ------------------------------------------------------------------ pdf_annots
EXPECTED_ANNOTS = [
    # (id, page, markupType, author, text, textSource, inReplyTo, color)
    ("fx-a1", 1, "cloud", "J. Rivera", "Revise door 105A swing to open out.", "contents", "", "#ff0000"),
    ("fx-a2", 1, "callout", "J. Rivera", "Widen corridor to 6'-0\" clear.", "contents", "", "#0000ff"),
    ("fx-a3", 1, "text box", "M. Chen", "Keep corridor at 5'-0\" clear per lease plan.", "rich text", "", "#0000ff"),
    ("fx-a4", 1, "strike-out", "M. Chen", "Delete note 4. Covered by spec.", "contents", "", "#ff0000"),
    ("fx-a5", 1, "note", "M. Chen", "Agreed. Check the hardware set too.", "contents", "fx-a1", "#ffff00"),
    ("fx-a6", 1, "text box", "J. Rivera", "Add dimension string to grid 3.", "contents", "", "#0000ff"),
    ("fx-b1", 2, "text box", "J. Rivera", "Confirm room name for 202: Live/Work Unit or Studio Unit?", "contents", "", "#0000ff"),
    ("fx-b2", 2, "cloud", "J. Rivera", "Verify door swing at Room 205.", "contents", "", "#ff0000"),
    ("fx-b3", 2, "text box", "J. Rivera", "Add dimension string to grid 3.", "contents", "", "#0000ff"),
]


def annot_tuples(res):
    return [(a["id"], a["page"], a["markupType"], a["author"], a["text"], a["textSource"],
             a["inReplyTo"], a["color"]) for a in res["annotations"]]


def test_pdf_annots_pypdf():
    res = P.extract(PDF, "pypdf")
    check(res is not None, "pypdf backend must be importable for this test")
    eq(annot_tuples(res), EXPECTED_ANNOTS, "pypdf annotations (popup skipped, reply linked)")
    eq(res["pageCount"], 2, "page count")
    eq([p["sheetCandidates"] for p in res["pages"]], [["A101", "A601"], ["A102"]], "sheet hints")
    eq(res["annotations"][0]["rect"], [0.2451, 0.4545, 0.2941, 0.5051], "cloud rect, top-left frame")
    eq(res["annotations"][0]["date"], "2026-10-15T09:30:00-04:00", "ISO date")


def test_pdf_annots_backend_parity():
    if P.pick_backend("pymupdf") is None:
        print("  SKIP parity: PyMuPDF not installed")
        return
    a, b = P.extract(PDF, "pypdf"), P.extract(PDF, "pymupdf")
    a.pop("backend")
    b.pop("backend")
    eq(b, a, "PyMuPDF and pypdf give the same records")


def test_pdf_annots_no_library_exit_3():
    code = ("import sys,runpy;sys.modules['pymupdf']=None;sys.modules['fitz']=None;"
            "sys.modules['pypdf']=None;sys.argv=['pdf_annots.py',%r];"
            "runpy.run_path(%r,run_name='__main__')" % (PDF, os.path.join(SCRIPTS, "pdf_annots.py")))
    p = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    eq(p.returncode, 3, "exit 3 when no PDF library")
    check(b"NO-PDF-LIBRARY" in p.stdout, "clear message when no PDF library")


def test_pdf_annots_check_flag():
    script = os.path.join(SCRIPTS, "pdf_annots.py")
    p = subprocess.run([sys.executable, script, "--check"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    eq(p.returncode, 0, "--check exits 0 when a library is usable")
    code = ("import sys,runpy;sys.modules['pymupdf']=None;sys.modules['fitz']=None;"
            "sys.modules['pypdf']=None;sys.argv=['pdf_annots.py','--check'];"
            "runpy.run_path(%r,run_name='__main__')" % script)
    p = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    eq(p.returncode, 3, "--check exits 3 when no library")


def test_consolidate_cli_wildcard_and_unicode_pipe():
    tmp = os.path.join(HERE, "_cli_tmp")
    os.makedirs(tmp)
    try:
        rec = {"kind": "markup-records", "records": [
            {"id": "u1", "sourceFile": "x.png", "page": 1, "sheet": "A101",
             "text": "Ramp slope %s 1:12 %s check, %s comment" % (chr(0x2265), chr(0x2192), chr(0x5F20)),
             "confidence": "low"}]}
        with open(os.path.join(tmp, "records-1.json"), "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False)
        out = os.path.join(tmp, "tracker.json")
        env = dict(os.environ)
        env.pop("PYTHONIOENCODING", None)
        env.pop("PYTHONUTF8", None)
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "consolidate.py"),
                            os.path.join(tmp, "records-*.json"), os.path.join(tmp, "annots-*.json"),
                            "--out", out], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        eq(p.returncode, 0, "CLI exit 0 (stderr: %r)" % p.stderr[-300:])
        check(b"WARN: no file matches" in p.stderr, "unmatched wildcard warns")
        with open(out, encoding="utf-8") as fh:
            t = json.load(fh)
        eq(t["items"][0]["text"], rec["records"][0]["text"], "non-ASCII text kept verbatim in the file")
    finally:
        for f in os.listdir(tmp):
            os.remove(os.path.join(tmp, f))
        os.rmdir(tmp)


def test_norm_rect_rotation():
    box = [0, 0, 200, 100]
    r = [10, 70, 30, 90]  # near the top left of the unrotated page
    eq(P.norm_rect(r, box, 0), [0.05, 0.1, 0.15, 0.3], "rotate 0")
    eq(P.norm_rect(r, box, 180), [0.85, 0.7, 0.95, 0.9], "rotate 180")
    eq(P.norm_rect(r, box, 90), [0.7, 0.05, 0.9, 0.15], "rotate 90 (top left goes to top right)")
    eq(P.norm_rect(r, box, 270), [0.1, 0.85, 0.3, 0.95], "rotate 270")


def test_rich_text_and_classify():
    eq(P.strip_rich_text("<body><p>A &amp; B</p><p>C</p></body>"), "A & B\nC", "rich text strip")
    eq(P.classify("Square", "", "C", False), "cloud", "Bluebeam rectangle cloud")
    eq(P.classify("Polygon", "", "", False), "polygon", "plain polygon is not a cloud")
    eq(P.classify("FreeText", "", "", True), "callout", "callout line makes a callout")


# ------------------------------------------------------------------ consolidate
def tracker(model=True):
    annots = P.extract(PDF, "pypdf")
    recs = C.annots_to_records(annots)
    with open(VISUAL, encoding="utf-8") as fh:
        vis = json.load(fh)
    tmp = os.path.join(HERE, "_annots.tmp.json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(annots, fh)
    try:
        records = C.load_records([tmp, VISUAL])
    finally:
        os.remove(tmp)
    check(len(records) == len(recs) + len(vis["records"]), "all records loaded")
    return C.consolidate(records, C.load_model(MODEL) if model else None), records


def test_consolidate_items():
    t, _ = tracker()
    got = [(it["n"], it["sheet"], it["text"], it["kind"], it["priority"], it["sources"])
           for it in t["items"]]
    want = [
        (1, "A101", "Widen corridor to 6'-0\" clear.", "change", "high", ["review-set.pdf p.1"]),
        (2, "A101", "Keep corridor at 5'-0\" clear per lease plan.", "change", "high", ["review-set.pdf p.1"]),
        (3, "A101", "ADD FE CABINET\nSEE 7/A503", "change", "high", ["review-set.pdf p.1"]),
        (4, "A101", "Revise door 105A swing to open out.", "change", "medium", ["review-set.pdf p.1"]),
        (5, "A101", "Delete note 4. Covered by spec.", "change", "medium", ["review-set.pdf p.1"]),
        (6, "A101", "Add dimension string to grid 3.", "change", "medium", ["review-set.pdf p.1"]),
        (7, "A102", "Confirm room name for 202: Live/Work Unit or Studio Unit?", "question", "medium",
         ["review-set.pdf p.2"]),
        (8, "A102", "Verify door swing at Room 205.", "question", "medium",
         ["review-set.pdf p.2", "photo-a102.png p.1"]),
        (9, "A102", "Add dimension string to grid 3.", "change", "medium", ["review-set.pdf p.2"]),
        (10, "A102", "FYI - owner OK w/ carpet", "fyi", "low", ["photo-a102.png p.1"]),
    ]
    eq(got, want, "tracker items")


def test_dedupe_merges_repeat_and_keeps_verbatim():
    t, records = tracker()
    by_n = dict((it["n"], it) for it in t["items"])
    eq(by_n[8]["memberIds"], ["fx-b2", "v-png-1"], "PDF p.2 comment and PNG note merge")
    eq(by_n[8]["textVariants"], ["Verify door swing at Rm 205"], "PNG wording kept verbatim")
    eq(by_n[4]["memberIds"], ["fx-a1", "v-p1-2"], "visual cloud merges with its annotation by region")
    eq(by_n[5]["memberIds"], ["fx-a4", "v-p1-3"], "visual strike-out merges by matchesAnnotation")
    eq([by_n[6]["memberIds"], by_n[9]["memberIds"]], [["fx-a6"], ["fx-b3"]],
       "same words on two different sheets stay two items")
    eq(t["counts"]["duplicatesMerged"], 3, "three duplicates merged")
    texts = set()
    for it in t["items"]:
        texts.add(it["text"])
        texts.update(it["textVariants"])
    for r in records:
        if r.get("text") and not r.get("inReplyTo"):
            check(r["text"] in texts, "verbatim text kept byte-identical: %r" % r["text"])
    eq(by_n[4]["replies"], [{"author": "M. Chen", "text": "Agreed. Check the hardware set too.", "id": "fx-a5"}],
       "reply attached to its parent, not a new item")


def test_conflict_flagged():
    t, _ = tracker()
    eq(t["conflicts"], [{"a": 1, "b": 2, "reason": "different values for corridor (6'-0\" vs 5'-0\")"}],
       "the two corridor comments conflict")
    eq(t["counts"]["conflicts"], 1, "one conflict")
    by_n = dict((it["n"], it) for it in t["items"])
    eq([by_n[1]["next"], by_n[2]["next"]], ["Decide between reviewers first"] * 2, "conflict next step")


def test_conflict_target_value_and_same_author():
    base = {"sourceFile": "x.pdf", "page": 1, "sheet": "A101", "kind": "change"}
    recs = [dict(base, id="1", text="Door 105A width", target="door 105A width", value="36in", author="A"),
            dict(base, id="2", text="Door 105A width please", target="Door 105A width", value="42in", author="B"),
            dict(base, id="3", text="Widen corridor to 6'-0\"", author="A", page=2),
            dict(base, id="4", text="Keep corridor at 5'-0\"", author="A", page=2)]
    t = C.consolidate(recs)
    eq(len(t["conflicts"]), 1, "target/value conflict found; same author is not a conflict")
    eq(t["conflicts"][0]["reason"], "same target 'door 105A width', different values", "reason text")


def test_next_steps_and_model_check():
    t, _ = tracker()
    by_n = dict((it["n"], it) for it in t["items"])
    eq([by_n[n]["next"] for n in (3, 4, 5, 6, 7, 10)],
       ["Model change -> am-safe-change", "Model change -> am-safe-change",
        "Drawing edit (notes, dimensions, details)", "Drawing edit (notes, dimensions, details)",
        "Answer the reviewer", "No action. Keep as a note"], "next steps")
    eq(t["unmatched"], [{"n": 3, "sheet": "A101", "missing": ["detail 7/A503: sheet A503 not in model"]}],
       "unmatched model references")
    eq(by_n[8]["modelCheck"], "Sheet A102 found (Second Floor Plan); Room 205 Live/Work Unit; Door 205A",
       "sheet, room and door matched in the Snowdon model")


def test_model_index_unescape():
    m = C.load_model(MODEL)
    names = dict((s["number"], s["name"]) for s in m["sheets"])
    eq(names.get("K101"), "Caf" + chr(0xE9) + " Kitchen", "IronPython ASCII escape reversed")


def test_schedules_and_csv():
    t, _ = tracker()
    s = C.schedules_json(t)
    eq(s["kind"], "schedules", "renderer kind")
    eq([x["name"] for x in s["schedules"]], ["Action tracker", "Conflicts", "Low confidence", "Not found in model"],
       "schedule names")
    eq([len(x["rows"]) for x in s["schedules"]], [10, 1, 1, 1], "row counts")
    for x in s["schedules"]:
        check(all(len(r) == len(x["columns"]) and all(isinstance(c, str) for c in r) for r in x["rows"]),
              "every cell is a string and rows match columns: %s" % x["name"])
    row3 = s["schedules"][0]["rows"][2]
    eq(row3[4], "[interpretation] Add a fire extinguisher (FE) cabinet in Room 106. See detail 7 on sheet A503.",
       "interpretation is labelled as such")


def test_no_model_no_unmatched_key():
    t, _ = tracker(model=False)
    check("unmatched" not in t, "without --model there is no unmatched list")


def run_all(verbose=True):
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    CHECKS[0] = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            if verbose:
                print("PASS %s" % name)
        except AssertionError as e:
            failed.append(name)
            if verbose:
                print("FAIL %s: %s" % (name, e))
    return len(tests), failed, CHECKS[0]


if __name__ == "__main__":
    n, failed, checks = run_all()
    print("%d test(s), %d failed, %d assertion(s) run" % (n, len(failed), checks))
    sys.exit(1 if failed or checks == 0 else 0)

# -*- coding: utf-8 -*-
"""CONSOLIDATE step for am-markup-intake: records -> one action tracker.

    python consolidate.py <in.json> [<in.json> ...] --out tracker.json
                          [--model model-index.json] [--csv tracker.csv]
                          [--schedules tracker.schedules.json] [--quiet]

Inputs (each file, detected by "kind"):
  "markup-records"   {"kind": "markup-records", "records": [ ... ]}  (from the
                     extraction subagents; a bare list of records also works)
  "pdf-annotations"  output of pdf_annots.py. Each annotation becomes a record
                     with its verbatim text. The sheet comes from a
                     "sheetMap" in a markup-records file, else from a single
                     sheetCandidate on that page.
--model: output of read_model_index.py (the agent run record, its "result",
  or the plain JSON). Adds a model check to each item and an "unmatched" list.

Writes tracker.json (kind "markup-tracker"), tracker.csv (UTF-8 with BOM) and
tracker.schedules.json (kind "schedules", for am-schedule-view render-table.ps1).
Default paths for --csv / --schedules sit next to --out.

Record fields (missing ones default to ""):
  id, sourceFile, page, sheet, location, markupType, text (VERBATIM, or
  "" for a drawn mark with no words), interpreted (marked as interpretation),
  kind (change|question|fyi), discipline, confidence (high|med|low), region
  {rect:[x0,y0,x1,y1] page fractions, desc}, author, date, target, value,
  matchesAnnotation (id of a pdf annotation the same mark already has),
  inReplyTo, textSource (annotation|visual).

Rules (deterministic; no text is ever rewritten):
  Dedupe   A record joins an earlier item when
           (a) it names it in matchesAnnotation, or
           (b) same source file + page and the regions overlap (>= 50 % of the
               smaller one) and the text is similar or one side has no text, or
           (c) same sheet, similar text (normalized, ratio >= 0.85), compatible
               location (no conflicting room/door/grid/detail tags), and - when
               both regions are on the same file page - the regions overlap.
           Text similarity uses a normalized copy (case, punctuation,
           abbreviations like Rm -> room). Every verbatim variant and every
           source is kept.
  Replies  A record with inReplyTo attaches to its parent item as a reply.
  Kind     From the record; else "?" or verify/confirm/clarify/check/why -> question,
           FYI/note:/for info -> fyi, else change.
  Conflict Two items on the same sheet with compatible locations, by different
           authors, and either the same "target" with a different "value", or
           (fallback) a shared subject word plus opposite verbs (add/remove,
           widen/keep, ...) or different dimension values.
  Priority high: conflict, or life-safety / code words; low: fyi; else medium.
  Next     question -> answer or RFI; fyi -> no action; change -> am-safe-change
           (model element), drawing edit (notes, dimensions, details), or
           consultant (non-architectural discipline).
Pure CPython 3.6+, ASCII source.
"""
import argparse
import csv
import difflib
import glob
import io
import json
import os
import re
import sys

SIM = 0.85
OVERLAP = 0.5
CONF_RANK = {"high": 3, "med": 2, "medium": 2, "low": 1, "": 0}
PRIO_RANK = {"high": 0, "medium": 1, "low": 2}

ABBREV = [
    (r"\brm\b", "room"), (r"\brms\b", "rooms"), (r"\bw/o\b", "without"), (r"\bw/", "with "),
    (r"\btyp\b", "typical"), (r"\bdim\b", "dimension"), (r"\bdims\b", "dimensions"),
    (r"\bclg\b", "ceiling"), (r"\bflr\b", "floor"), (r"\bdr\b", "door"), (r"\bwdw\b", "window"),
    (r"\bcorr\b", "corridor"), (r"\bext\b", "exterior"), (r"\bint\b", "interior"),
    (r"\bmin\b", "minimum"), (r"\bmax\b", "maximum"), (r"\bpls\b", "please"),
    (r"\b&\b", "and"),
]
STOP = set("""the a an and or of to at in on for with by per from this that these those
is are be been it its as into onto all any each see note please typical revise verify
confirm check provide add delete remove keep clear unit""".split())
OPPOSITES = [
    ({"add", "provide", "install", "include"}, {"remove", "delete", "omit", "eliminate"}),
    ({"widen", "increase", "enlarge", "extend", "raise"},
     {"narrow", "decrease", "reduce", "shorten", "lower", "keep", "maintain", "retain"}),
    ({"relocate", "move", "shift"}, {"keep", "maintain", "retain"}),
]
LIFE_SAFETY = re.compile(r"\b(fire|egress|exit|rated|rating|sprinkler|extinguisher|ada|"
                         r"accessib\w*|code|life safety|smoke|structural|guard ?rail|handrail)\b", re.I)
DRAWING_WORDS = re.compile(r"\b(note|notes|dimension\w*|text|leader|keynote|tag|label|detail|"
                           r"callout|title|annotation|line ?weight|hatch|legend)\b", re.I)
MODEL_WORDS = re.compile(r"\b(door|window|wall|room|swing|ceiling|floor|stair|ramp|cabinet|"
                         r"casework|partition|column|corridor|furniture|fixture|roof|rename|renumber|"
                         r"sheet number|finish)\w*", re.I)
QUESTION_START = re.compile(r"^\s*(verify|confirm|clarify|check|why|can|could|should|is|are|do|does)\b", re.I)
FYI_START = re.compile(r"^\s*(fyi|note:|for info|for your information|info only)", re.I)

ENTITY_RES = [
    ("room", re.compile(r"\b(?:room|rm)\.?\s*#?\s*([A-Z]?\d{2,4}[A-Z]?)\b", re.I)),
    ("door", re.compile(r"\b(?:door|dr)\.?\s*#?\s*([A-Z]?\d{1,4}[A-Z]{0,3})\b", re.I)),
    ("window", re.compile(r"\b(?:window|wdw)\.?\s*#?\s*([A-Z]?\d{1,4}[A-Z]{0,2})\b", re.I)),
    ("grid", re.compile(r"\bgrid(?:\s*line)?s?\s+([A-Z]{1,2}(?:\.\d)?|\d{1,2}(?:\.\d)?)\b", re.I)),
    ("detail", re.compile(r"\b(\d{1,2})\s*/\s*([A-Z]{1,3}-?\d{2,4}(?:\.\d{1,2})?)\b", re.I)),
]
DIM_RE = re.compile(r"\d+\s*'\s*-?\s*\d+(?:\s*\d+/\d+)?\s*\"?|\d+(?:\.\d+)?\s*(?:mm|cm|m|in|ft|\")")


# ---------------------------------------------------------------- loading
def _unescape(obj):
    """Reverse the IronPython ASCII escape of read_model_index.py ("\\u00e9" -> e-acute)."""
    if isinstance(obj, dict):
        return dict((k, _unescape(v)) for k, v in obj.items())
    if isinstance(obj, list):
        return [_unescape(v) for v in obj]
    if isinstance(obj, str) and "\\" in obj:
        return re.sub(r"\\u([0-9a-fA-F]{4})|\\\\",
                      lambda m: chr(int(m.group(1), 16)) if m.group(1) else "\\", obj)
    return obj


def load_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def load_model(path):
    obj = load_json(path)
    if isinstance(obj, dict) and isinstance(obj.get("result"), dict):
        obj = obj["result"]
    if isinstance(obj, dict) and isinstance(obj.get("payload"), str):
        obj = json.loads(obj["payload"])
    if not isinstance(obj, dict) or "sheets" not in obj:
        raise ValueError("%s is not a model index (no 'sheets')" % path)
    if obj.get("escaped"):
        obj = _unescape(obj)
    return obj


def annots_to_records(doc):
    """pdf_annots.py output -> records. Text stays verbatim; nothing is interpreted."""
    fname = doc.get("file", "")
    cands = dict((str(p["page"]), p.get("sheetCandidates") or []) for p in doc.get("pages", []))
    out = []
    for a in doc.get("annotations", []):
        pg = str(a.get("page", ""))
        sheet = ""
        if len(cands.get(pg, [])) == 1:
            sheet = cands[pg][0]
        out.append({
            "id": a.get("id", ""), "sourceFile": fname, "page": a.get("page", ""),
            "sheet": sheet, "location": "", "markupType": a.get("markupType", ""),
            "text": a.get("text", ""), "interpreted": "", "kind": "",
            "discipline": "", "confidence": "high", "author": a.get("author", ""),
            "date": a.get("date", ""), "region": {"rect": a.get("rect")},
            "inReplyTo": a.get("inReplyTo", ""), "textSource": "annotation",
        })
    return out


def expand_paths(paths):
    """Expand wildcards here: PowerShell and cmd pass "annots-*.json" to Python unexpanded.
    A pattern with no match (for example no annots files after pdf_annots.py exit 3)
    prints a WARN and is skipped."""
    out = []
    for p in paths:
        if any(ch in p for ch in "*?["):
            hits = sorted(glob.glob(p))
            if not hits:
                sys.stderr.write("WARN: no file matches %s (skipped)\n" % p)
            out.extend(hits)
        else:
            out.append(p)
    return out


def load_records(paths):
    """Read every input. A "sheetMap" ({"<file>": {"<page>": "A101"}}) in any
    markup-records file sets the sheet of records from that file page that have none
    (the title-block reading of the visual pass wins over a text-layer guess)."""
    recs, sheet_map = [], {}
    for p in expand_paths(paths):
        obj = load_json(p)
        if isinstance(obj, list):
            batch = obj
        elif obj.get("kind") == "pdf-annotations":
            batch = annots_to_records(obj)
        elif "records" in obj:
            batch = obj["records"]
            for f, pages in (obj.get("sheetMap") or {}).items():
                for pg, sh in pages.items():
                    sheet_map[(f, str(pg))] = sh
        else:
            raise ValueError("%s: unknown input (expected markup-records or pdf-annotations)" % p)
        recs.extend(batch)
    for r in recs:
        mapped = sheet_map.get((r.get("sourceFile") or "", str(r.get("page", ""))))
        if mapped and (r.get("textSource") == "annotation" or not r.get("sheet")):
            r["sheet"] = mapped
    return recs


# ---------------------------------------------------------------- text helpers
def norm_text(s):
    s = (s or "").lower()
    for pat, rep in ABBREV:
        s = re.sub(pat, rep, s)
    s = re.sub(r"[^a-z0-9/'\"\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(".-'\" ")


def norm_sheet(s):
    return re.sub(r"[\s\-_.]", "", (s or "").upper())


def similar(a, b):
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= SIM


def entities(*texts):
    found = {}
    for t in texts:
        for kind, rx in ENTITY_RES:
            for m in rx.finditer(t or ""):
                val = "%s/%s" % (m.group(1), m.group(2).upper()) if kind == "detail" else m.group(1).upper()
                found.setdefault(kind, set()).add(val)
    return found


def locations_compatible(a, b):
    ea, eb = entities(a.get("location"), a.get("text")), entities(b.get("location"), b.get("text"))
    for kind in set(ea) & set(eb):
        if not (ea[kind] & eb[kind]):
            return False
    la, lb = norm_text(a.get("location")), norm_text(b.get("location"))
    if la and lb and not (set(ea) & set(eb)) and la != lb:
        return difflib.SequenceMatcher(None, la, lb).ratio() >= 0.6
    return True


def rect_of(r):
    reg = r.get("region") or {}
    rect = reg.get("rect") if isinstance(reg, dict) else None
    if isinstance(rect, list) and len(rect) == 4:
        return [float(v) for v in rect]
    return None


def overlap(r1, r2):
    """Intersection area over the smaller area (0..1)."""
    if not r1 or not r2:
        return 0.0
    ix = max(0.0, min(r1[2], r2[2]) - max(r1[0], r2[0]))
    iy = max(0.0, min(r1[3], r2[3]) - max(r1[1], r2[1]))
    a1 = max(1e-9, (r1[2] - r1[0]) * (r1[3] - r1[1]))
    a2 = max(1e-9, (r2[2] - r2[0]) * (r2[3] - r2[1]))
    return (ix * iy) / min(a1, a2)


def same_page(a, b):
    return (a.get("sourceFile") or "") == (b.get("sourceFile") or "") and \
        str(a.get("page", "")) == str(b.get("page", "")) and bool(a.get("sourceFile"))


def classify_kind(r):
    k = (r.get("kind") or "").lower()
    if k in ("change", "question", "fyi"):
        return k
    t = r.get("text") or r.get("interpreted") or ""
    if FYI_START.search(t):
        return "fyi"
    if "?" in t or QUESTION_START.search(t):
        return "question"
    return "change"


# ---------------------------------------------------------------- core
def is_duplicate(item, rec):
    """Does record rec describe the same markup as the (merged) item?"""
    for m in item["members"]:
        ma = rec.get("matchesAnnotation")
        if ma and ma == m.get("id"):
            return True
        if same_page(m, rec):
            ov = overlap(rect_of(m), rect_of(rec))
            if ov >= OVERLAP and (not m.get("text") or not rec.get("text")
                                  or similar(m.get("text"), rec.get("text"))):
                return True
    first = item["members"][0]
    if not rec.get("text") or not first.get("text"):
        return False
    if norm_sheet(first.get("sheet")) != norm_sheet(rec.get("sheet")) or not norm_sheet(rec.get("sheet")):
        return False
    if not similar(first.get("text"), rec.get("text")):
        return False
    if not locations_compatible(first, rec):
        return False
    for m in item["members"]:
        if same_page(m, rec) and rect_of(m) and rect_of(rec) and overlap(rect_of(m), rect_of(rec)) == 0:
            return False  # same words, different spot on the same page: two markups
    return True


def dedupe(records):
    items = []
    for rec in records:
        hit = None
        for it in items:
            if is_duplicate(it, rec):
                hit = it
                break
        if hit is None:
            items.append({"members": [rec]})
        else:
            hit["members"].append(rec)
    return items


def opposite(t1, t2):
    w1, w2 = set(norm_text(t1).split()), set(norm_text(t2).split())
    for left, right in OPPOSITES:
        if (w1 & left and w2 & right) or (w1 & right and w2 & left):
            return True
    return False


def content_words(t):
    return set(w for w in re.findall(r"[a-z]{4,}", norm_text(t)) if w not in STOP)


def conflict_reason(a, b):
    """a, b are merged items. Return a reason string or ''."""
    if norm_sheet(a["sheet"]) != norm_sheet(b["sheet"]) or not norm_sheet(a["sheet"]):
        return ""
    if not locations_compatible(a["members"][0], b["members"][0]):
        return ""
    if a["authors"] and b["authors"] and not (set(a["authors"]) ^ set(b["authors"])):
        return ""  # same reviewer(s) on both sides: a revision, not a conflict
    ta, tb = a.get("target", ""), b.get("target", "")
    if ta and tb and norm_text(ta) == norm_text(tb):
        if norm_text(a.get("value")) != norm_text(b.get("value")):
            return "same target '%s', different values" % ta
        return ""
    t1 = a["text"] or a["interpreted"]
    t2 = b["text"] or b["interpreted"]
    shared = content_words(t1) & content_words(t2)
    if not shared:
        return ""
    d1 = set(re.sub(r"\s", "", d) for d in DIM_RE.findall(t1))
    d2 = set(re.sub(r"\s", "", d) for d in DIM_RE.findall(t2))
    if d1 and d2 and d1 != d2:
        return "different values for %s (%s vs %s)" % (
            ", ".join(sorted(shared)), ", ".join(sorted(d1)), ", ".join(sorted(d2)))
    if opposite(t1, t2):
        return "opposite requests about %s" % ", ".join(sorted(shared))
    return ""


def next_step(item):
    k = item["kind"]
    disc = (item.get("discipline") or "").strip()
    arch = (not disc) or disc.lower().startswith("arch") or disc.upper() == "A"
    if item["conflictWith"]:
        return "Decide between reviewers first"
    if k == "fyi":
        return "No action. Keep as a note"
    if k == "question":
        return "Answer the reviewer" if arch else "RFI to %s consultant" % disc
    if not arch:
        return "Send to %s consultant" % disc
    body = " ".join([item["text"], item["interpreted"], item["markupType"]])
    if item["markupType"] == "strike-out" or DRAWING_WORDS.search(body):
        if MODEL_WORDS.search(body) and not DRAWING_WORDS.search(item["text"]):
            return "Model change -> am-safe-change"
        return "Drawing edit (notes, dimensions, details)"
    if MODEL_WORDS.search(body):
        return "Model change -> am-safe-change"
    return "Review and assign"


def build_items(records):
    replies = [r for r in records if r.get("inReplyTo")]
    roots = [r for r in records if not r.get("inReplyTo")]
    merged = dedupe(roots)
    items = []
    for n, m in enumerate(merged):
        mem = m["members"]
        texts = []
        for r in mem:
            t = r.get("text") or ""
            if t and t not in texts:
                texts.append(t)
        interp = [r.get("interpreted") for r in mem if r.get("interpreted")]
        best = max(mem, key=lambda r: CONF_RANK.get((r.get("confidence") or "").lower(), 0))
        conf = (best.get("confidence") or "").lower()
        conf = "med" if conf == "medium" else conf
        authors = []
        for r in mem:
            if r.get("author") and r["author"] not in authors:
                authors.append(r["author"])
        sources = []
        for r in mem:
            s = "%s p.%s" % (r.get("sourceFile") or "?", r.get("page") or 1)
            if s not in sources:
                sources.append(s)
        loc = next((r.get("location") for r in mem if r.get("location")), "")
        item = {
            "key": n, "sheet": next((r.get("sheet") for r in mem if r.get("sheet")), ""),
            "location": loc, "text": texts[0] if texts else "",
            "textVariants": texts[1:], "interpreted": interp[0] if interp else "",
            "markupType": mem[0].get("markupType") or "",
            "kind": classify_kind(dict(mem[0], text=texts[0] if texts else "",
                                       interpreted=interp[0] if interp else "")),
            "discipline": next((r.get("discipline") for r in mem if r.get("discipline")), ""),
            "confidence": conf or "med", "authors": authors, "sources": sources,
            "target": next((r.get("target") for r in mem if r.get("target")), ""),
            "value": next((r.get("value") for r in mem if r.get("value")), ""),
            "memberIds": [r.get("id", "") for r in mem], "members": mem,
            "replies": [], "conflictWith": [], "conflictReason": [],
            "duplicates": len(mem) - 1,
        }
        if not item["text"]:
            item["text"] = "(drawn, no text)"
        items.append(item)
    by_member = {}
    for it in items:
        for mid in it["memberIds"]:
            if mid:
                by_member[mid] = it
    orphans = []
    for r in replies:
        parent = by_member.get(r.get("inReplyTo"))
        rep = {"author": r.get("author", ""), "text": r.get("text", ""), "id": r.get("id", "")}
        if parent is None:
            orphans.append(rep)
        else:
            parent["replies"].append(rep)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            why = conflict_reason(items[i], items[j])
            if why:
                items[i]["conflictWith"].append(j)
                items[j]["conflictWith"].append(i)
                items[i]["conflictReason"].append(why)
                items[j]["conflictReason"].append(why)
    for it in items:
        body = " ".join([it["text"], it["interpreted"]] + it["textVariants"])
        if it["conflictWith"] or LIFE_SAFETY.search(body):
            it["priority"] = "high"
        elif it["kind"] == "fyi":
            it["priority"] = "low"
        else:
            it["priority"] = "medium"
        it["next"] = next_step(it)
    order = sorted(items, key=lambda it: (norm_sheet(it["sheet"]) or "~", PRIO_RANK[it["priority"]], it["key"]))
    num = {}
    for n, it in enumerate(order, 1):
        num[it["key"]] = n
    for it in order:
        it["n"] = num[it["key"]]
        it["conflictWith"] = [num[items[j]["key"]] for j in it["conflictWith"]]
    return order, orphans


# ---------------------------------------------------------------- model mapping
def map_to_model(items, model):
    sheets = dict((norm_sheet(s["number"]), s) for s in model.get("sheets", []))
    rooms = dict((r["number"].upper(), r) for r in model.get("rooms", []))
    doors = set(m.upper() for m in model.get("doorMarks", []))
    windows = set(m.upper() for m in model.get("windowMarks", []))
    unmatched = []
    for it in items:
        notes = []
        miss = []
        sh = sheets.get(norm_sheet(it["sheet"])) if it["sheet"] else None
        if not it["sheet"]:
            miss.append("no sheet number")
        elif sh:
            notes.append("Sheet %s found (%s)" % (sh["number"], sh["name"]))
        else:
            miss.append("sheet %s not in model" % it["sheet"])
        ents = entities(it["location"], it["text"], *it["textVariants"])
        for rn in sorted(ents.get("room", [])):
            if rn in rooms:
                notes.append("Room %s %s" % (rn, rooms[rn]["name"]))
            else:
                miss.append("room %s not in model" % rn)
        for d in sorted(ents.get("door", [])):
            (notes.append("Door %s" % d) if d in doors else miss.append("door %s not in model" % d))
        for w in sorted(ents.get("window", [])):
            (notes.append("Window %s" % w) if w in windows else miss.append("window %s not in model" % w))
        for ref in sorted(ents.get("detail", [])):
            det, sn = ref.split("/", 1)
            target = sheets.get(norm_sheet(sn))
            if target is None:
                miss.append("detail %s: sheet %s not in model" % (ref, sn))
            elif det not in [v.get("detail") for v in target.get("views", [])]:
                miss.append("detail %s: no view %s on %s" % (ref, det, sn))
            else:
                notes.append("Detail %s" % ref)
        it["modelCheck"] = "; ".join(notes + ["NOT FOUND: " + m for m in miss])
        if miss:
            unmatched.append({"n": it["n"], "sheet": it["sheet"], "missing": miss})
    return unmatched


# ---------------------------------------------------------------- output
COLUMNS = ["#", "Sheet", "Location", "Markup text (verbatim)", "Request (interpreted)", "Type",
           "Priority", "Confidence", "Source", "Next step", "Model check", "Flags"]


def flags(it):
    f = []
    if it["conflictWith"]:
        f.append("CONFLICT with #%s: %s" % (", #".join(str(c) for c in it["conflictWith"]),
                                            "; ".join(it["conflictReason"])))
    if it["confidence"] == "low":
        f.append("LOW CONFIDENCE")
    if it["duplicates"]:
        f.append("merged %d duplicate(s)" % it["duplicates"])
    if it["textVariants"]:
        f.append("also written as: " + " | ".join(it["textVariants"]))
    if it["replies"]:
        f.append("replies: " + " | ".join("%s: %s" % (r["author"], r["text"]) for r in it["replies"]))
    if it["authors"]:
        f.append("by " + ", ".join(it["authors"]))
    return "; ".join(f)


def row(it):
    return [str(it["n"]), it["sheet"] or "(unknown)", it["location"], it["text"],
            ("[interpretation] " + it["interpreted"]) if it["interpreted"] else "",
            it["kind"], it["priority"], it["confidence"], ", ".join(it["sources"]), it["next"],
            it.get("modelCheck", ""), flags(it)]


def public_item(it):
    out = dict((k, v) for k, v in it.items() if k not in ("members", "key"))
    return out


def consolidate(records, model=None):
    items, orphans = build_items(records)
    unmatched = map_to_model(items, model) if model else None
    counts = {
        "records": len(records), "items": len(items),
        "duplicatesMerged": sum(it["duplicates"] for it in items),
        "replies": sum(len(it["replies"]) for it in items),
        "change": sum(1 for it in items if it["kind"] == "change"),
        "question": sum(1 for it in items if it["kind"] == "question"),
        "fyi": sum(1 for it in items if it["kind"] == "fyi"),
        "high": sum(1 for it in items if it["priority"] == "high"),
        "conflicts": sum(1 for it in items if it["conflictWith"]) // 2,
        "lowConfidence": sum(1 for it in items if it["confidence"] == "low"),
    }
    conflicts = []
    for it in items:
        for c in it["conflictWith"]:
            if it["n"] < c:
                conflicts.append({"a": it["n"], "b": c, "reason": "; ".join(it["conflictReason"])})
    if unmatched is not None:
        counts["unmatched"] = len(unmatched)
    tracker = {"kind": "markup-tracker", "counts": counts, "columns": COLUMNS,
               "items": [public_item(it) for it in items], "conflicts": conflicts,
               "orphanReplies": orphans}
    if unmatched is not None:
        tracker["unmatched"] = unmatched
        tracker["modelDocument"] = model.get("document", "")
    return tracker


def schedules_json(tracker):
    by_n = dict((it["n"], it) for it in tracker["items"])
    rows = [row(it) for it in tracker["items"]]
    scheds = [{"name": "Action tracker", "id": "", "category": "Markup tracker",
               "columns": COLUMNS, "rows": rows, "rowKinds": ["body"] * len(rows)}]
    crow = []
    for c in tracker["conflicts"]:
        a, b = by_n[c["a"]], by_n[c["b"]]
        crow.append(["#%d vs #%d" % (c["a"], c["b"]), a["sheet"], a["text"], ", ".join(a["authors"]),
                     b["text"], ", ".join(b["authors"]), c["reason"]])
    scheds.append({"name": "Conflicts", "id": "", "category": "Markup tracker",
                   "columns": ["Items", "Sheet", "Request A", "By A", "Request B", "By B", "Why"],
                   "rows": crow, "rowKinds": ["body"] * len(crow)})
    low = [row(it) for it in tracker["items"] if it["confidence"] == "low"]
    scheds.append({"name": "Low confidence", "id": "", "category": "Markup tracker",
                   "columns": COLUMNS, "rows": low, "rowKinds": ["body"] * len(low)})
    if "unmatched" in tracker:
        um = [[str(u["n"]), u["sheet"] or "(unknown)", "; ".join(u["missing"])] for u in tracker["unmatched"]]
        scheds.append({"name": "Not found in model", "id": "", "category": "Markup tracker",
                       "columns": ["#", "Sheet", "Not found"], "rows": um, "rowKinds": ["body"] * len(um)})
    return {"kind": "schedules", "schedules": scheds,
            "pageTitle": "Markup action tracker",
            "banner": "Read only. This list was built from review markups; nothing in Revit was changed."}


def write_csv(tracker, path):
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for it in tracker["items"]:
            w.writerow(row(it))


def summary(tracker, top=10):
    c = tracker["counts"]
    lines = ["%d record(s) -> %d item(s): %d change, %d question, %d FYI. %d duplicate(s) merged, "
             "%d reply(ies) attached." % (c["records"], c["items"], c["change"], c["question"], c["fyi"],
                                         c["duplicatesMerged"], c["replies"]),
             "High priority: %d. Conflicts: %d. Low confidence: %d.%s" % (
                 c["high"], c["conflicts"], c["lowConfidence"],
                 (" Not found in model: %d." % c["unmatched"]) if "unmatched" in c else "")]
    lines.append("Top items:")
    for it in tracker["items"][:top]:
        lines.append("  #%d [%s] %s %s: \"%s\" -> %s" % (it["n"], it["priority"], it["sheet"] or "?",
                                                       it["location"], it["text"], it["next"]))
    for cf in tracker["conflicts"]:
        lines.append("CONFLICT #%d vs #%d: %s" % (cf["a"], cf["b"], cf["reason"]))
    return "\n".join(lines)


def safe_stdout():
    """A piped stdout on Windows uses the locale code page; a comment with an arrow or a
    CJK name would raise after the files are written. Print those as escapes instead."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Consolidate markup records into an action tracker.")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model")
    ap.add_argument("--csv")
    ap.add_argument("--schedules")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    safe_stdout()
    try:
        records = load_records(a.inputs)
        model = load_model(a.model) if a.model else None
    except (IOError, OSError, ValueError) as e:
        print("FAIL: %s" % e)
        return 1
    if not records:
        print("FAIL: no records in the input files")
        return 1
    tracker = consolidate(records, model)
    base = os.path.splitext(a.out)[0]
    csv_path = a.csv or base + ".csv"
    sch_path = a.schedules or base + ".schedules.json"
    for p in (a.out, csv_path, sch_path):
        d = os.path.dirname(os.path.abspath(p))
        if not os.path.isdir(d):
            os.makedirs(d)
    with io.open(a.out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(tracker, indent=1, ensure_ascii=False) + "\n")
    write_csv(tracker, csv_path)
    with io.open(sch_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(schedules_json(tracker), indent=1, ensure_ascii=False) + "\n")
    print("OK: wrote %s, %s, %s" % (a.out, csv_path, sch_path))
    if not a.quiet:
        print(summary(tracker))
    return 0


if __name__ == "__main__":
    sys.exit(main())

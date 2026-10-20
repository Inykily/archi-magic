# -*- coding: utf-8 -*-
"""EXECUTE step for the sheet renumber recipe (run_modify / --mode=dry_run|modify).

inputs: {"preview_path": "C:/.../x.preview.json"}   (forward slashes are fine)
    or  {"preview": {...preview dict...}}

Replays the preview's ordered "steps" ([id, from, to]) inside ONE transaction,
so the user's Keep/Discard in Revit is all-or-nothing. Before it changes
anything it checks that every sheet still has the number in the preview's
"before" rows; if not, it stops with no change.

result = {"rows": [[id, number], ...] for ALL sheets after the steps,
          "steps_applied": n, "partial": false, "escaped": bool}
A dry run returns the same result and Revit rolls everything back.
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import io
import json
import sys

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"  # see read_sheets.py: IronPython result encoder is ASCII-only


def txt(s):
    if not ESCAPE:
        return s
    out = []
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif ord(c) < 128:
            out.append(c)
        else:
            out.append("\\u%04x" % ord(c))
    return "".join(out)


def eid_int(element_id):
    try:
        return int(element_id.Value)        # Revit 2024+
    except AttributeError:
        return int(element_id.IntegerValue)  # removed in Revit 2026


def load_preview():
    if inputs.get("preview"):
        return inputs["preview"]
    path = inputs.get("preview_path")
    if not path:
        raise ValueError("inputs needs preview_path or preview")
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.loads(f.read())


preview = load_preview()
if preview.get("kind") != "change-preview":
    raise ValueError("Not a change-preview file.")
if preview.get("blocked"):
    raise ValueError("The preview is BLOCKED. Resolve its blocking warnings first.")
steps = preview.get("steps") or []
if not steps:
    raise ValueError("The preview has no steps. Nothing to apply.")

sheets = {}
for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
    sheets[eid_int(vs.Id)] = vs

# Stale-state guard: the model must still match the preview's "before" rows.
stale = []
before_ids = set()
for row in preview["before"]:
    sid, number = int(row[0]), row[1]
    before_ids.add(sid)
    vs = sheets.get(sid)
    if vs is None:
        stale.append("sheet %s (%s) no longer exists" % (sid, txt(number)))
    elif vs.SheetNumber != number:
        stale.append("sheet %s is now %s, preview says %s" % (sid, txt(vs.SheetNumber), txt(number)))
for sid in sheets:
    if sid not in before_ids:
        stale.append("sheet %s (%s) is new since the preview" % (sid, txt(sheets[sid].SheetNumber)))
if stale:
    raise ValueError("Model changed since the preview. Read and preview again. " + "; ".join(stale[:10]))

t = DB.Transaction(doc, preview.get("title") or "Shift sheet numbers")
t.Start()
done = 0
try:
    for st in steps:
        sid, old, new = int(st[0]), st[1], st[2]
        vs = sheets[sid]
        if vs.SheetNumber != old:
            raise ValueError("step %d: sheet %s is %s, expected %s" % (done + 1, sid, txt(vs.SheetNumber), txt(old)))
        vs.SheetNumber = new
        done += 1
    rows = sorted([[sid, txt(vs.SheetNumber)] for sid, vs in sheets.items()])
    t.Commit()
except Exception:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    raise

result = {"rows": rows, "steps_applied": done, "partial": False, "escaped": ESCAPE}

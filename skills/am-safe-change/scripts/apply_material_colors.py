# -*- coding: utf-8 -*-
"""EXECUTE step for the material-colors recipe (run_modify / --mode=dry_run|modify).

inputs: {"preview_path": "C:/.../x.preview.json"}   (forward slashes are fine)
    or  {"preview": {...preview dict...}}

For each preview step, in ONE transaction (the user's Keep/Discard is all-or-nothing):
    1. Set the material Color (shading) when the step has one.
    2. Set the Surface Foreground Pattern color when the step has one.
Same colors as scripts/lib/material_colors.py computes.

Before it changes anything it checks every step's material still has the
preview's "before" colors. If not, it stops with "Model changed since
the preview" and changes nothing.

result = {"rows": [{"id", "shading", "surface_pattern_color", "status"}],
          "steps_applied": n, "partial": True, "escaped": bool}
A dry run returns the same result and Revit rolls everything back.
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import io
import json

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"


def make_id(i):
    try:
        import System
        return DB.ElementId(System.Int64(i))  # Revit 2024+ (2026 has only Int64)
    except Exception:
        return DB.ElementId(int(i))


def load_preview(inputs):
    if "preview_path" in inputs:
        with io.open(inputs["preview_path"], "r", encoding="utf-8-sig") as f:
            return json.load(f)
    if "preview" in inputs:
        return inputs["preview"]
    raise ValueError("inputs need preview_path or preview.")


def rgb(color):
    if color is None:
        return None
    try:
        return [int(color.Red), int(color.Green), int(color.Blue)]
    except Exception:
        return None


def pattern_color(mat):
    try:
        return rgb(mat.SurfaceForegroundPatternColor)
    except Exception:
        return None


def state(mat):
    return {"shading": rgb(mat.Color),
            "surface_pattern_color": pattern_color(mat)}


preview = load_preview(inputs)
if preview.get("kind") != "change-preview":
    raise ValueError("Not a change-preview file.")
if preview.get("blocked"):
    raise ValueError("The preview is BLOCKED. Decide its blocking warnings first.")
steps = preview.get("steps") or []
if not steps or "expectAfter" not in steps[0]:
    raise ValueError("The preview has no material-color steps. Nothing to apply.")

# Stale-state guard.
materials = {}
stale = []
for st in steps:
    eid = int(st["id"])
    mat = doc.GetElement(make_id(eid))
    if mat is None:
        stale.append("material %s no longer exists" % eid)
        continue
    materials[eid] = mat
    now = state(mat)
    want = st["expect"]
    for key in ("shading", "surface_pattern_color"):
        if want.get(key) is not None and now.get(key) != list(want[key]):
            stale.append("material %s %s is %s, preview says %s"
                         % (eid, key, now.get(key), want.get(key)))
if stale:
    raise ValueError("Model changed since the preview. Read and preview again. " + "; ".join(stale[:10]))

t = DB.Transaction(doc, preview.get("title") or "Change material colors")
t.Start()
done = 0
try:
    for st in steps:
        mat = materials[int(st["id"])]
        if st.get("shading") is not None:
            r, g, b = st["shading"]
            mat.Color = DB.Color(int(r), int(g), int(b))
        if st.get("surface_pattern_color") is not None:
            r, g, b = st["surface_pattern_color"]
            mat.SurfaceForegroundPatternColor = DB.Color(int(r), int(g), int(b))
        done += 1
    t.Commit()
except Exception:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    raise

rows = []
for st in steps:
    eid = int(st["id"])
    mat = doc.GetElement(make_id(eid))
    after = state(mat) if mat is not None else {"shading": None, "surface_pattern_color": None}
    rows.append({"id": eid, "shading": after["shading"],
                 "surface_pattern_color": after["surface_pattern_color"],
                 "status": "done" if mat is not None else "missing after apply"})

result = {"rows": rows, "steps_applied": done, "partial": True, "escaped": ESCAPE}

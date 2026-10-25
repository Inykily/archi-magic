# -*- coding: utf-8 -*-
"""am-rhino-area-report: READ-ONLY area report of the open Rhino 8 document, by layer.

Run with the rhino-mcp tool run_python (CPython 3 inside Rhino). Uses __rhino_doc__ only (never
scriptcontext.doc or rhinoscriptsyntax). Prints ONE JSON object to stdout; changes nothing.

What counts as an area:
  - closed planar curves (outlines),
  - planar surfaces: a Brep or Extrusion with ONE planar face (a polysurface is skipped: its total
    surface area is not a floor area),
  - hatches (unless include_hatches is false).
Everything else is skipped with a reason.

Optional inputs: put a line `INPUTS = {...}` before this script.
  group_key        user text key to group by inside each layer, for example "Room" (default: none)
  include_hatches  true/false (default true)
  include_hidden   true/false (default false: hidden objects are skipped)
  layers           list of layer full paths; only these and their sublayers (default: all)
  max_skipped_ids  cap on listed skipped ids (default 50)

The pure functions at the top have no Rhino imports (tests/test_rhino_area_report.py).
"""
import json

INPUTS = globals().get("INPUTS") or {}
# Rhino can print its own lines to stdout (seen live: "Creating meshes... Press Esc to cancel"),
# so the result is the ONE line that starts with this prefix. Parse the JSON after it.
RESULT_PREFIX = "AM_RESULT "

SQFT_PER_SQM = 10.763910416709722


def to_m2(area_doc_units, meters_per_unit):
    """Area in document units squared -> square meters."""
    return area_doc_units * meters_per_unit * meters_per_unit


def m2_to_ft2(m2):
    return m2 * SQFT_PER_SQM


def layer_selected(path, wanted):
    """True when no filter is given, or path is a wanted layer or one of its sublayers."""
    if not wanted:
        return True
    return any(path == w or path.startswith(w + "::") for w in wanted)


def summarize(items, meters_per_unit):
    """items: list of {"layer", "group", "area"} in document units.
    Returns rows sorted by layer then group, plus totals."""
    acc = {}
    for it in items:
        key = (it["layer"], it.get("group") or "")
        a = acc.setdefault(key, {"count": 0, "area": 0.0})
        a["count"] += 1
        a["area"] += it["area"]
    rows = []
    for (layer, group) in sorted(acc):
        a = acc[(layer, group)]
        m2 = to_m2(a["area"], meters_per_unit)
        rows.append({"layer": layer, "group": group, "count": a["count"],
                     "area_doc_units": round(a["area"], 4),
                     "area_m2": round(m2, 3), "area_ft2": round(m2_to_ft2(m2), 2)})
    total_doc = sum(a["area"] for a in acc.values())
    total_m2 = to_m2(total_doc, meters_per_unit)
    totals = {"count": sum(a["count"] for a in acc.values()), "area_doc_units": round(total_doc, 4),
              "area_m2": round(total_m2, 3), "area_ft2": round(m2_to_ft2(total_m2), 2)}
    return rows, totals


def csv_table(rows, unit_label):
    """Header and rows for the CSV the agent writes (it quotes fields itself)."""
    header = ["layer", "group", "count", "area_%s2" % unit_label, "area_m2", "area_ft2"]
    return header, [[r["layer"], r["group"], r["count"], r["area_doc_units"], r["area_m2"], r["area_ft2"]] for r in rows]


UNIT_LABELS = {"Millimeters": "mm", "Centimeters": "cm", "Meters": "m", "Inches": "in", "Feet": "ft"}


def main(doc):
    import Rhino
    D = Rhino.DocObjects
    G = Rhino.Geometry
    group_key = INPUTS.get("group_key") or ""
    include_hatches = INPUTS.get("include_hatches", True) is not False
    include_hidden = bool(INPUTS.get("include_hidden", False))
    wanted = list(INPUTS.get("layers") or [])
    max_ids = int(INPUTS.get("max_skipped_ids") or 50)

    unit_name = str(doc.ModelUnitSystem)
    mpu = Rhino.RhinoMath.UnitScale(doc.ModelUnitSystem, Rhino.UnitSystem.Meters)
    tol = doc.ModelAbsoluteTolerance

    settings = D.ObjectEnumeratorSettings()
    settings.HiddenObjects = include_hidden
    settings.LockedObjects = True
    items, skipped = [], {}

    def skip(reason, obj):
        s = skipped.setdefault(reason, [])
        s.append(str(obj.Id))

    for o in doc.Objects.GetObjectList(settings):
        layer = doc.Layers[o.Attributes.LayerIndex].FullPath
        if not layer_selected(layer, wanted):
            continue
        g = o.Geometry
        area = None
        if isinstance(g, G.Curve):
            if not g.IsClosed:
                skip("open curve", o); continue
            if not g.IsPlanar(tol):
                skip("closed curve not planar", o); continue
            amp = G.AreaMassProperties.Compute(g)
            area = amp.Area if amp else None
        elif isinstance(g, (G.Brep, G.Extrusion)):
            b = g.ToBrep() if isinstance(g, G.Extrusion) else g
            if b is None or b.Faces.Count != 1:
                skip("polysurface (use one planar surface or a closed curve)", o); continue
            if not b.Faces[0].IsPlanar(tol):
                skip("surface not planar", o); continue
            amp = G.AreaMassProperties.Compute(b)
            area = amp.Area if amp else None
        elif isinstance(g, G.Hatch):
            if not include_hatches:
                skip("hatch (include_hatches is false)", o); continue
            amp = G.AreaMassProperties.Compute(g)
            area = amp.Area if amp else None
        else:
            continue  # points, text, meshes, blocks: not areas, not worth listing
        if area is None:
            skip("area could not be computed", o); continue
        group = o.Attributes.GetUserString(group_key) if group_key else ""
        items.append({"layer": layer, "group": group or ("(no %s)" % group_key if group_key else ""), "area": area})

    rows, totals = summarize(items, mpu)
    label = UNIT_LABELS.get(unit_name, unit_name)
    header, csv_rows = csv_table(rows, label)
    return {
        "status": "ok", "document": doc.Name or "(unsaved)", "units": unit_name, "unit_label": label,
        "group_key": group_key, "rows": rows, "totals": totals,
        "skipped": dict((k, {"count": len(v), "ids": v[:max_ids]}) for k, v in skipped.items()),
        "header": header, "csv_rows": csv_rows,
    }


if "__rhino_doc__" in globals():
    try:
        print(RESULT_PREFIX + json.dumps(main(__rhino_doc__)))
    except Exception as ex:  # report, never crash silently
        import traceback
        print(RESULT_PREFIX + json.dumps({"status": "error", "error": "%s: %s" % (type(ex).__name__, ex),
                          "traceback": traceback.format_exc()}))

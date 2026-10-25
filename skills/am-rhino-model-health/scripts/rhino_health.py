# -*- coding: utf-8 -*-
"""am-rhino-model-health: READ-ONLY health check of the open Rhino 8 document.

Run with the rhino-mcp tool run_python (CPython 3 inside Rhino). The tool injects __rhino_doc__;
this script never uses scriptcontext.doc or rhinoscriptsyntax. It prints ONE JSON object to stdout;
run_python returns stdout (a pure-JSON stdout comes back parsed). It changes nothing.

Optional inputs: put a line `INPUTS = {...}` before this script.
  max_items  cap on listed ids per finding (default 50)

The pure functions at the top have no Rhino imports, so tests can load this file with plain
Python (tests/test_rhino_health.py). The Rhino part runs only when __rhino_doc__ exists.
"""
import json

INPUTS = globals().get("INPUTS") or {}
# Rhino can print its own lines to stdout (seen live: "Creating meshes... Press Esc to cancel"),
# so the result is the ONE line that starts with this prefix. Parse the JSON after it.
RESULT_PREFIX = "AM_RESULT "

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}

# Tolerance sanity, expressed in meters so it works for any document unit.
# Coarser than 1 mm makes joins and booleans fail on architectural detail;
# finer than 0.001 mm (1e-6 m) slows Rhino and fails imports from other tools.
TOL_COARSE_M = 0.001
TOL_FINE_M = 1e-6


def tolerance_findings(unit_name, abs_tol, meters_per_unit):
    """Findings about the absolute tolerance. meters_per_unit converts one document unit to meters."""
    out = []
    if abs_tol <= 0:
        return [{"code": "TOL_ZERO", "severity": "error",
                 "message": "Absolute tolerance is %s. Set it in Options > Units." % abs_tol}]
    tol_m = abs_tol * meters_per_unit
    if tol_m > TOL_COARSE_M:
        out.append({"code": "TOL_COARSE", "severity": "warn",
                    "message": "Absolute tolerance %g %s (= %g mm) is coarser than 1 mm. Joins and booleans can fail." % (abs_tol, unit_name, tol_m * 1000)})
    elif tol_m < TOL_FINE_M:
        out.append({"code": "TOL_FINE", "severity": "warn",
                    "message": "Absolute tolerance %g %s (= %g mm) is finer than 0.001 mm. This slows Rhino and can break exports." % (abs_tol, unit_name, tol_m * 1000)})
    return out


def subtree_object_counts(layers, counts):
    """layers: list of dicts {index, parent} (parent = index or None). counts: {layer index: objects}.
    Returns {layer index: objects on the layer and all its sublayers}."""
    children = {}
    for l in layers:
        children.setdefault(l["parent"], []).append(l["index"])
    memo = {}

    def total(i):
        if i in memo:
            return memo[i]
        t = counts.get(i, 0) + sum(total(c) for c in children.get(i, []))
        memo[i] = t
        return t

    return dict((l["index"], total(l["index"])) for l in layers)


def empty_layers(layers, counts):
    """Full paths of layers with no objects on them or on any sublayer."""
    sub = subtree_object_counts(layers, counts)
    return sorted(l["path"] for l in layers if sub[l["index"]] == 0)


def unused_block_names(definitions, top_level_refs):
    """definitions: {index: {"name": str, "nested": [indexes of blocks used inside it]}}.
    top_level_refs: indexes of blocks placed directly in the model.
    A block is used when it is placed, or nested in a used block. Returns unused names, sorted."""
    used = set()
    stack = [i for i in top_level_refs if i in definitions]
    while stack:
        i = stack.pop()
        if i in used:
            continue
        used.add(i)
        stack.extend(j for j in definitions[i].get("nested", []) if j in definitions)
    return sorted(d["name"] for i, d in definitions.items() if i not in used)


def is_small(diagonal, abs_tol):
    """An object smaller than 10 x tolerance is usually a stray or a modeling accident."""
    return 0 <= diagonal < 10 * abs_tol


def rank(findings):
    """Errors first, then warnings, then info; stable inside each level."""
    return sorted(findings, key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))


def main(doc):
    import os
    import Rhino
    D = Rhino.DocObjects
    G = Rhino.Geometry
    max_items = int(INPUTS.get("max_items") or 50)

    unit = doc.ModelUnitSystem
    unit_name = str(unit)
    mpu = Rhino.RhinoMath.UnitScale(unit, Rhino.UnitSystem.Meters)
    tol = doc.ModelAbsoluteTolerance

    settings = D.ObjectEnumeratorSettings()
    settings.HiddenObjects = True
    settings.LockedObjects = True
    objs = list(doc.Objects.GetObjectList(settings))

    layers = []
    for l in doc.Layers:
        if l.IsDeleted:
            continue
        parent = doc.Layers.FindId(l.ParentLayerId)
        layers.append({"index": l.Index, "path": l.FullPath,
                       "parent": parent.Index if parent is not None else None})
    path_by_index = dict((l["index"], l["path"]) for l in layers)

    by_type, by_layer, counts = {}, {}, {}
    invalid, small, open_polys, default_objs = [], [], [], []
    hidden = locked = 0
    top_refs = set()
    for o in objs:
        t = str(o.ObjectType)
        by_type[t] = by_type.get(t, 0) + 1
        li = o.Attributes.LayerIndex
        counts[li] = counts.get(li, 0) + 1
        lp = path_by_index.get(li, "?")
        by_layer[lp] = by_layer.get(lp, 0) + 1
        if lp == "Default":
            default_objs.append(str(o.Id))
        if o.IsHidden:
            hidden += 1
        if o.IsLocked:
            locked += 1
        g = o.Geometry
        if g is not None and not g.IsValid:
            invalid.append(str(o.Id))
        if g is not None:
            bb = g.GetBoundingBox(True)
            if bb.IsValid and is_small(bb.Diagonal.Length, tol):
                small.append(str(o.Id))
        if isinstance(g, G.Brep) and g.Faces.Count > 1 and not g.IsSolid:
            open_polys.append(str(o.Id))
        if isinstance(o, D.InstanceObject):
            top_refs.add(o.InstanceDefinition.Index)

    defs = {}
    for d in doc.InstanceDefinitions.GetList(True):
        nested = [x.InstanceDefinition.Index for x in d.GetObjects() if isinstance(x, D.InstanceObject)]
        defs[d.Index] = {"name": d.Name, "nested": nested}
    unused = unused_block_names(defs, top_refs)
    empties = empty_layers(layers, counts)

    findings = tolerance_findings(unit_name, tol, mpu)
    def add(code, severity, ids, message):
        if ids:
            findings.append({"code": code, "severity": severity, "count": len(ids),
                             "ids": ids[:max_items], "message": message})
    add("INVALID_GEOMETRY", "error", invalid, "Objects with invalid geometry. Run Check or ExtractBadSrf, then rebuild them.")
    add("SMALL_OBJECTS", "warn", small, "Objects smaller than 10 x tolerance. Often strays: SelSmall to review.")
    add("OPEN_POLYSURFACES", "info", open_polys, "Polysurfaces that are not closed solids. Fine for surfaces; a problem if a solid was meant (ShowEdges > Naked).")
    add("DEFAULT_LAYER_OBJECTS", "info", default_objs, "Objects on the Default layer. am-rhino-layer-cleanup can move them.")
    if empties:
        findings.append({"code": "EMPTY_LAYERS", "severity": "info", "count": len(empties),
                         "paths": empties[:max_items], "message": "Layers with no objects. am-rhino-layer-cleanup can delete them."})
    if unused:
        findings.append({"code": "UNUSED_BLOCKS", "severity": "info", "count": len(unused),
                         "names": unused[:max_items], "message": "Block definitions placed nowhere. Purge removes them."})

    size = None
    if doc.Path and os.path.exists(doc.Path):
        size = os.path.getsize(doc.Path)
    return {
        "status": "ok",
        "document": doc.Name or "(unsaved)",
        "file_size_mb": round(size / 1048576.0, 2) if size is not None else None,
        "units": unit_name, "absolute_tolerance": tol,
        "angle_tolerance_deg": doc.ModelAngleToleranceDegrees,
        "object_count": len(objs), "hidden": hidden, "locked": locked,
        "by_type": by_type, "by_layer": by_layer,
        "layer_count": len(layers), "block_definitions": len(defs),
        "findings": rank(findings),
    }


if "__rhino_doc__" in globals():
    try:
        print(RESULT_PREFIX + json.dumps(main(__rhino_doc__)))
    except Exception as ex:  # report, never crash silently
        import traceback
        print(RESULT_PREFIX + json.dumps({"status": "error", "error": "%s: %s" % (type(ex).__name__, ex),
                          "traceback": traceback.format_exc()}))

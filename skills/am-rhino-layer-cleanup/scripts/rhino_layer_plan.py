# -*- coding: utf-8 -*-
"""am-rhino-layer-cleanup, step 1: READ-ONLY plan for tidying the layers of the open Rhino 8 document.

Run with the rhino-mcp tool run_python. Uses __rhino_doc__ only. Prints ONE JSON object; changes nothing.

The plan lists:
  - empty_layers: layers with no objects on them or on any sublayer (hidden and locked objects
    count), never the current layer and never "Default"; ordered children first, ready to delete,
  - duplicate_names: layer paths that differ only by case, spaces, "_" or "-" (report only; merging
    is the user's call),
  - default_objects: objects on the Default layer (to move to a layer the user picks),
  - target_layers: existing layer paths, for the user to pick a target from.
Give the parts the user approves, unchanged, to rhino_layer_apply.py.

Optional inputs: put a line `INPUTS = {...}` before this script.
  max_items  cap on listed object ids (default 500)

Pure functions at the top have no Rhino imports (tests/test_rhino_layer_cleanup.py).
"""
import json
import re

INPUTS = globals().get("INPUTS") or {}
# Rhino can print its own lines to stdout (seen live: "Creating meshes... Press Esc to cancel"),
# so the result is the ONE line that starts with this prefix. Parse the JSON after it.
RESULT_PREFIX = "AM_RESULT "

PROTECTED_NAMES = ("Default",)


def normalize_name(path):
    """Case-, space-, '_' and '-' insensitive form of a layer path, segment by segment."""
    return "::".join(re.sub(r"[\s_\-]+", "", seg).lower() for seg in path.split("::"))


def duplicate_groups(paths):
    """Groups (sorted lists) of 2+ paths that look like the same layer. Sorted for stable output."""
    groups = {}
    for p in paths:
        groups.setdefault(normalize_name(p), []).append(p)
    return sorted(sorted(g) for g in groups.values() if len(g) > 1)


def empty_layer_plan(layers, counts, current_index):
    """layers: [{"index", "id", "path", "parent"}]; counts: {index: objects on that layer}.
    Returns deletable empty layers as [{"id", "path", "depth"}], deepest first, then by path.
    A layer is deletable when its whole subtree holds no objects, it is not the current layer,
    its subtree does not hold the current layer, and it is not a protected name."""
    children = {}
    for l in layers:
        children.setdefault(l["parent"], []).append(l["index"])
    by_index = dict((l["index"], l) for l in layers)
    memo = {}

    def subtree(i):
        if i not in memo:
            memo[i] = [i] + [x for c in children.get(i, []) for x in subtree(c)]
        return memo[i]

    out = []
    for l in layers:
        tree = subtree(l["index"])
        if any(counts.get(i, 0) for i in tree):
            continue
        if current_index in tree:
            continue
        if l["path"] in PROTECTED_NAMES:
            continue
        out.append({"id": l["id"], "path": l["path"], "depth": l["path"].count("::")})
    return sorted(out, key=lambda x: (-x["depth"], x["path"]))


def main(doc):
    import Rhino
    D = Rhino.DocObjects
    max_items = int(INPUTS.get("max_items") or 500)

    settings = D.ObjectEnumeratorSettings()
    settings.HiddenObjects = True
    settings.LockedObjects = True
    objs = list(doc.Objects.GetObjectList(settings))

    layers = []
    for l in doc.Layers:
        if l.IsDeleted:
            continue
        parent = doc.Layers.FindId(l.ParentLayerId)
        layers.append({"index": l.Index, "id": str(l.Id), "path": l.FullPath,
                       "parent": parent.Index if parent is not None else None})
    counts, default_ids = {}, []
    default_index = doc.Layers.FindByFullPath("Default", -1)
    for o in objs:
        li = o.Attributes.LayerIndex
        counts[li] = counts.get(li, 0) + 1
        if li == default_index and default_index >= 0:
            default_ids.append(str(o.Id))

    empties = empty_layer_plan(layers, counts, doc.Layers.CurrentLayerIndex)
    return {
        "status": "ok", "document": doc.Name or "(unsaved)",
        "layer_count": len(layers),
        "empty_layers": empties,
        "duplicate_names": duplicate_groups([l["path"] for l in layers]),
        "default_objects": {"count": len(default_ids), "ids": default_ids[:max_items],
                            "truncated": len(default_ids) > max_items},
        "target_layers": sorted(l["path"] for l in layers if l["path"] not in PROTECTED_NAMES),
        "current_layer": doc.Layers.CurrentLayer.FullPath,
    }


if "__rhino_doc__" in globals():
    try:
        print(RESULT_PREFIX + json.dumps(main(__rhino_doc__)))
    except Exception as ex:  # report, never crash silently
        import traceback
        print(RESULT_PREFIX + json.dumps({"status": "error", "error": "%s: %s" % (type(ex).__name__, ex),
                          "traceback": traceback.format_exc()}))

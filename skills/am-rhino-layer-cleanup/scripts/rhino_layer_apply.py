# -*- coding: utf-8 -*-
"""am-rhino-layer-cleanup, step 2: APPLY an approved layer plan to the open Rhino 8 document.

CHANGES THE MODEL. Run only after the user saw the plan from rhino_layer_plan.py and chose "Apply".
Rhino has no Keep/Discard step: the only gates are the user's answer and Claude Code's permission
prompt for run_python. All changes go into ONE undo record, so one Undo in Rhino reverses them.

Inputs: put a line `INPUTS = {...}` before this script. Use the plan's values unchanged.
  delete_layer_ids      list of layer ids (from plan.empty_layers[].id) to delete
  move_object_ids       list of object ids (from plan.default_objects.ids) to move
  move_to_layer         full path of an EXISTING layer (from plan.target_layers)

Every item is checked again before it changes, because the model can change between the plan
and the apply:
  - a layer is deleted only if it still exists, is still empty (whole subtree, hidden and locked
    objects included), is not the current layer and is not "Default";
  - an object is moved only if it still exists and is still on the Default layer.
Anything that fails a check is skipped with a reason; it never stops the other items.
Prints ONE JSON object: what changed and what was skipped.
"""
import json

INPUTS = globals().get("INPUTS") or {}
# Rhino can print its own lines to stdout (seen live: "Creating meshes... Press Esc to cancel"),
# so the result is the ONE line that starts with this prefix. Parse the JSON after it.
RESULT_PREFIX = "AM_RESULT "


def delete_order(items):
    """items: [{"id", "path"}]. Deepest layers first, so a parent is empty when its turn comes."""
    return sorted(items, key=lambda x: (-x["path"].count("::"), x["path"]))


def validate_inputs(inputs):
    """Returns a list of problems with the inputs (empty list = usable)."""
    problems = []
    dl = inputs.get("delete_layer_ids") or []
    mo = inputs.get("move_object_ids") or []
    if not isinstance(dl, list) or not isinstance(mo, list):
        problems.append("delete_layer_ids and move_object_ids must be lists")
    if mo and not inputs.get("move_to_layer"):
        problems.append("move_object_ids given without move_to_layer")
    if not dl and not mo:
        problems.append("nothing to do: both lists are empty")
    return problems


def main(doc):
    import System
    import Rhino
    D = Rhino.DocObjects
    problems = validate_inputs(INPUTS)
    if problems:
        return {"status": "invalid_inputs", "problems": problems}

    settings = D.ObjectEnumeratorSettings()
    settings.HiddenObjects = True
    settings.LockedObjects = True
    counts = {}

    def recount():
        # Counted AFTER the moves (seen live: counts taken before the moves let a layer that just
        # received objects look empty; only Rhino's own refusal kept it).
        counts.clear()
        for o in doc.Objects.GetObjectList(settings):
            li = o.Attributes.LayerIndex
            counts[li] = counts.get(li, 0) + 1

    def subtree_empty(layer):
        stack = [layer]
        while stack:
            l = stack.pop()
            if counts.get(l.Index, 0):
                return False
            kids = l.GetChildren()
            if kids:
                stack.extend(k for k in kids if not k.IsDeleted)
        return True

    deleted, moved, skipped = [], [], []
    default_index = doc.Layers.FindByFullPath("Default", -1)
    undo = doc.BeginUndoRecord("am-rhino-layer-cleanup")
    try:
        # 1. Move objects first: a layer emptied by the move is not deleted in the same run.
        target = INPUTS.get("move_to_layer") or ""
        mo = INPUTS.get("move_object_ids") or []
        if mo:
            ti = doc.Layers.FindByFullPath(target, -1)
            if ti < 0:
                skipped.extend({"id": i, "reason": "target layer '%s' does not exist" % target} for i in mo)
            else:
                for sid in mo:
                    try:
                        obj = doc.Objects.FindId(System.Guid(sid))
                    except Exception:
                        obj = None
                    if obj is None:
                        skipped.append({"id": sid, "reason": "object no longer exists"}); continue
                    if obj.Attributes.LayerIndex != default_index:
                        skipped.append({"id": sid, "reason": "object is no longer on Default"}); continue
                    attrs = obj.Attributes.Duplicate()
                    attrs.LayerIndex = ti
                    if doc.Objects.ModifyAttributes(obj, attrs, True):
                        moved.append(sid)
                    else:
                        skipped.append({"id": sid, "reason": "Rhino refused to move it (locked layer or object?)"})
        # 2. Delete layers, deepest first, judged on the counts after the moves.
        recount()
        items = []
        for lid in INPUTS.get("delete_layer_ids") or []:
            try:
                layer = doc.Layers.FindId(System.Guid(lid))
            except Exception:
                layer = None
            if layer is None or layer.IsDeleted:
                skipped.append({"id": lid, "reason": "layer no longer exists"}); continue
            items.append({"id": lid, "path": layer.FullPath, "layer": layer})
        current = doc.Layers.CurrentLayerIndex
        for it in delete_order(items):
            layer = it["layer"]
            if layer.FullPath == "Default" or layer.Index == current:
                skipped.append({"id": it["id"], "reason": "current or Default layer"}); continue
            if not subtree_empty(layer):
                skipped.append({"id": it["id"], "reason": "layer is no longer empty"}); continue
            if doc.Layers.Delete(layer.Index, True):
                deleted.append(it["path"])
            else:
                skipped.append({"id": it["id"], "reason": "Rhino refused to delete it"})
    finally:
        doc.EndUndoRecord(undo)
    doc.Views.Redraw()
    return {"status": "ok", "deleted_layers": deleted, "moved_objects": len(moved),
            "moved_to": target if moved else "", "skipped": skipped,
            "undo": "One Undo in Rhino reverses all of this (undo record 'am-rhino-layer-cleanup')."}


if "__rhino_doc__" in globals():
    try:
        print(RESULT_PREFIX + json.dumps(main(__rhino_doc__)))
    except Exception as ex:  # report, never crash silently
        import traceback
        print(RESULT_PREFIX + json.dumps({"status": "error", "error": "%s: %s" % (type(ex).__name__, ex),
                          "traceback": traceback.format_exc()}))

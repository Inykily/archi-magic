# -*- coding: utf-8 -*-
"""EXECUTE step for the texture-repath recipe (run_modify / --mode=dry_run|modify).

inputs: {"preview_path": "C:/.../x.preview.json"}   (forward slashes are fine)
    or  {"preview": {...preview dict...}}

For each preview step, in ONE transaction (the user's Keep/Discard is
all-or-nothing), grouped by appearance asset so one asset edit fixes
every material that shares it:
    1. Check the slot still holds the preview's "before" path (the
       stale-state guard). If not, stop with "Model changed since
       the preview" and change nothing.
    2. Open an AppearanceAssetEditScope for the asset, get the editable
       asset, find the bitmap string property for the slot, check
       IsValidValue for the new path, then set Value.
    3. Commit the scope.

The scope API shape (constructor with the document and the asset id,
GetEditableAsset, Commit(True) inside one transaction) follows issue
#90, which ran this pattern live. The recipe's dry run is the check
that it still holds on the user's Revit version: if the dry run
fails, stop and report before any real change.

result = {"rows": [{"asset_id", "slot", "material_ids", "before",
                     "after", "status"}],
          "steps_applied": n, "partial": True, "escaped": bool}
A dry run returns the same result and Revit rolls everything back.
Runs under IronPython 2.7 and CPython 3 (no f-strings).
"""
import io
import json

from pyrevit.api import DB

ESCAPE = sys.platform == "cli"

BITMAP_PROPERTY = "unifiedbitmapbitmap"


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


def normalize_path(path):
    if path is None:
        return ""
    return str(path).strip().replace("/", "\\")


def asset_properties(asset):
    """The properties of a rendering asset, as a list."""
    try:
        props = asset.GetProperties()
        if props is not None:
            return list(props)
    except Exception:
        pass
    try:
        return list(asset)
    except Exception:
        return []


def find_property(asset, name):
    """One property of an asset by name (case-insensitive), or None."""
    for prop in asset_properties(asset):
        try:
            if prop.Name is not None and prop.Name.lower() == name.lower():
                return prop
        except Exception:
            continue
    return None


def connected_asset(prop):
    """The single asset connected to a property, or None."""
    try:
        single = prop.GetSingleConnectedAsset()
        if single is not None:
            return single
    except Exception:
        pass
    try:
        connected = prop.GetAllConnectedAssets()
        if connected is not None:
            connected = list(connected)
            if len(connected) == 1:
                return connected[0]
    except Exception:
        pass
    return None


def find_bitmap_property(asset, slot):
    """The UnifiedbitmapBitmap string property for a slot path, or None.

    Walks the dot-joined connected-property path, then finds the
    bitmap string property on the asset at the end of the path.
    """
    current = asset
    for segment in slot.split("."):
        if not segment:
            continue
        prop = find_property(current, segment)
        if prop is None:
            return None
        current = connected_asset(prop)
        if current is None:
            return None
    return find_property(current, BITMAP_PROPERTY)


def read_slot(asset_id, slot):
    """The current bitmap string for one (asset, slot), or None."""
    elem = doc.GetElement(make_id(asset_id))  # noqa: F821
    if elem is None:
        return None
    try:
        rendering = elem.GetRenderingAsset()
    except Exception:
        return None
    if rendering is None:
        return None
    prop = find_bitmap_property(rendering, slot)
    if prop is None:
        return None
    try:
        return prop.Value
    except Exception:
        return None


preview = load_preview(inputs)
if preview.get("kind") != "change-preview":
    raise ValueError("Not a change-preview file.")
if preview.get("blocked"):
    raise ValueError("The preview is BLOCKED. Decide its blocking warnings first.")
steps = preview.get("steps") or []
if not steps or "expectAfter" not in steps[0]:
    raise ValueError("The preview has no texture-repath steps. Nothing to apply.")

# Stale-state guard: every step's slot must still hold its "before" path.
stale = []
for st in steps:
    now = read_slot(st["asset_id"], st["slot"])
    if now is None:
        stale.append("asset %s slot %s cannot be read"
                     % (st["asset_id"], st["slot"]))
    elif normalize_path(now) != normalize_path(st["expect"]):
        stale.append("asset %s slot %s is %s, preview says %s"
                     % (st["asset_id"], st["slot"], now, st["expect"]))
if stale:
    raise ValueError("Model changed since the preview. Read and preview again. "
                     + "; ".join(stale[:10]))

by_asset = {}
asset_order = []
for st in steps:
    key = st["asset_id"]
    if key not in by_asset:
        by_asset[key] = []
        asset_order.append(key)
    by_asset[key].append(st)

t = DB.Transaction(doc, preview.get("title") or "Repath texture images")  # noqa: F821
t.Start()
done = 0
try:
    for asset_id in asset_order:
        scope = None
        try:
            scope = DB.AppearanceAssetEditScope(doc, make_id(asset_id))  # noqa: F821
            editable = scope.GetEditableAsset()
            for st in by_asset[asset_id]:
                prop = find_bitmap_property(editable, st["slot"])
                if prop is None:
                    raise ValueError("asset %s slot %s has no bitmap property"
                                     % (asset_id, st["slot"]))
                new_path = st["expectAfter"]
                try:
                    valid = prop.IsValidValue(new_path)
                except Exception:
                    valid = True
                if not valid:
                    raise ValueError("asset %s slot %s refuses path %s"
                                     % (asset_id, st["slot"], new_path))
                prop.Value = new_path
                done += 1
            scope.Commit(True)
        except Exception:
            if scope is not None:
                try:
                    scope.Cancel()
                except Exception:
                    pass
            raise
    t.Commit()
except Exception:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    raise

rows = []
for st in steps:
    after = read_slot(st["asset_id"], st["slot"])
    rows.append({"asset_id": st["asset_id"], "slot": st["slot"],
                 "material_ids": st["material_ids"],
                 "before": st["expect"], "after": after,
                 "status": "ok" if normalize_path(after or "") ==
                           normalize_path(st["expectAfter"] or "") else "mismatch"})

result = {"rows": rows, "steps_applied": done, "partial": False,
          "escaped": ESCAPE}
if ESCAPE:
    print("apply_texture_repath: %d steps applied" % done)

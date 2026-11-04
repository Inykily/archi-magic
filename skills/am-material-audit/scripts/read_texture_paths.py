# -*- coding: utf-8 -*-
"""am-material-audit, texture-path mode: read-only texture image paths.

Submit with the pyrevit MCP tool run_query (or `pyrevit agent run <this file> --mode=query`).
IronPython 2.7 compatible: no f-strings, no type hints, no print kwargs,
ASCII only. The script changes nothing and writes no files. It sets `result`
to a JSON-safe dict:

  {prefix, model, revit_year, timestamp, path, matched,
   materials: [{id, name, asset_id, asset_name,
                asset_unreadable: bool,
                slots: [{slot, path}]}],
   notes: [str, ...]}

For each material it reads the appearance asset element, then
`AppearanceAssetElement.GetRenderingAsset()`, then follows the connected
properties and reads every `UnifiedBitmap.UnifiedbitmapBitmap` string.
`slot` is the connected-property path that leads to the bitmap, for
example `generic_diffuse` or `generic_bump_map`. A material whose
rendering asset is missing or has no properties is reported with
`asset_unreadable: true` and no slots, not silently dropped.

Optional inputs (dict): {"prefix": "Floor Finish"}. An empty or missing
prefix reads every material in the model: the texture question is usually
asked about the whole model, not one name group.

The paths are returned raw on purpose. Classification (ok, in the
Autodesk library, missing, empty) happens outside Revit in
scripts/lib/texture_paths.py, where the file system and the installed
library can be checked. The read script never tests a path itself.
"""
import datetime
import sys

from pyrevit.api import DB

try:
    INPUTS = inputs  # noqa: F821  (injected by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}

PREFIX = INPUTS.get("prefix", "")
if PREFIX is None:
    PREFIX = ""
PREFIX = PREFIX.strip()

BITMAP_PROPERTY = "unifiedbitmapbitmap"

NOTES = [
    "Paths are returned raw. Classification happens in texture_paths.py.",
    "Bare file names are resolved only against the installed Autodesk "
    "library, not against Revit's Additional render appearance paths option.",
]


def eid(element_id):
    """ElementId -> int. Revit 2024+ has .Value; 2023 and older only .IntegerValue."""
    if hasattr(element_id, "Value"):
        return int(element_id.Value)
    return int(element_id.IntegerValue)


IRONPYTHON = sys.platform == "cli"


def jsonable(value):
    """Make non-ASCII text survive the runtime's json.dumps on IronPython 2.7.

    Same method as read_materials.py: hand the encoder the UTF-8 bytes as
    latin-1 code points, so that decode returns the real text.
    """
    if isinstance(value, dict):
        return dict((jsonable(k), jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if IRONPYTHON and isinstance(value, basestring):  # noqa: F821
        if any(ord(c) > 127 for c in value):
            return value.encode("utf-8").decode("latin-1")
    return value


def safe_name(element):
    try:
        return element.Name
    except Exception:
        return "(no name)"


def asset_properties(asset):
    """The properties of a rendering asset, as a list.

    GetProperties is the documented enumeration. Iterating the asset is
    the fallback for runtimes where that call is missing.
    """
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


def connected_assets(prop):
    """Assets connected to one property, or an empty list."""
    try:
        connected = prop.GetAllConnectedAssets()
        if connected is not None:
            return list(connected)
    except Exception:
        pass
    try:
        single = prop.GetSingleConnectedAsset()
        if single is not None:
            return [single]
    except Exception:
        pass
    return []


def walk_asset(asset, slot, out):
    """Collect (slot, bitmap path) pairs from one rendering asset.

    Follows connected properties depth-first. A string property named
    UnifiedbitmapBitmap records its value under the slot path that led
    to its asset: the top-level property name for a direct bitmap, or a
    dot-joined path for a nested one. Returns the number of properties
    visited, so the caller can tell an empty asset from an asset that
    simply has no bitmap slots.
    """
    visited = 0
    for prop in asset_properties(asset):
        visited += 1
        try:
            name = prop.Name
        except Exception:
            continue
        if name is None:
            continue
        children = connected_assets(prop)
        if children:
            child_slot = name if not slot else slot + "." + name
            for child in children:
                try:
                    visited += walk_asset(child, child_slot, out)
                except Exception:
                    continue
            continue
        if name.lower() != BITMAP_PROPERTY:
            continue
        try:
            value = prop.Value
        except Exception:
            continue
        if isinstance(value, basestring):  # noqa: F821
            out.append((slot, value))
    return visited


def collect_texture_paths(prefix):
    """Materials (prefix-filtered, or all when prefix is empty) with slots."""
    found = []
    needle = prefix.lower()
    for mat in DB.FilteredElementCollector(doc).OfClass(DB.Material):  # noqa: F821
        name = safe_name(mat)
        if needle and not name.lower().startswith(needle):
            continue
        asset_id = -1
        asset_name = ""
        unreadable = False
        slots = []
        try:
            asset_elem_id = mat.AppearanceAssetId
        except Exception:
            asset_elem_id = None
        if asset_elem_id is not None:
            try:
                asset_id = eid(asset_elem_id)
            except Exception:
                asset_id = -1
            if asset_id > 0:
                try:
                    asset_elem = doc.GetElement(asset_elem_id)  # noqa: F821
                except Exception:
                    asset_elem = None
                if asset_elem is not None:
                    asset_name = safe_name(asset_elem)
                    try:
                        rendering = asset_elem.GetRenderingAsset()
                    except Exception:
                        rendering = None
                    if rendering is None:
                        unreadable = True
                    else:
                        try:
                            pairs = []
                            seen = walk_asset(rendering, "", pairs)
                        except Exception:
                            pairs = []
                            seen = 0
                            unreadable = True
                        if seen == 0 and not unreadable:
                            # An asset with no properties at all reads as
                            # empty, the shape the issue reports for
                            # built-in system and analytical materials.
                            # An asset with properties but no bitmap
                            # slots stays readable with zero slots.
                            unreadable = True
                        for slot, path in pairs:
                            slots.append({"slot": slot, "path": path})
                else:
                    unreadable = True
            else:
                unreadable = True
        else:
            unreadable = True
        found.append({
            "id": eid(mat.Id),
            "name": name,
            "asset_id": asset_id,
            "asset_name": asset_name,
            "asset_unreadable": unreadable,
            "slots": slots,
        })
    found.sort(key=lambda m: m["name"].lower())
    return found


if doc is None or doc.IsFamilyDocument:  # noqa: F821
    result = {"error": "no_project_document",
              "message": "Open a Revit project (.rvt), not a family, then run again."}
else:
    materials = collect_texture_paths(PREFIX)
    slot_count = sum(len(m["slots"]) for m in materials)
    unreadable_count = len([m for m in materials if m["asset_unreadable"]])
    result = {
        "prefix": PREFIX,
        "model": doc.Title,  # noqa: F821
        "revit_year": str(app.VersionNumber),  # noqa: F821
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "path": doc.PathName or "",  # noqa: F821
        "matched": len(materials),
        "materials": materials,
        "notes": NOTES,
    }
    result = jsonable(result)
    print("am-material-audit textures: %d materials, %d image slots, "
          "%d unreadable assets" % (len(materials), slot_count, unreadable_count))

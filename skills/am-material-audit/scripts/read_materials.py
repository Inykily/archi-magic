# -*- coding: utf-8 -*-
"""am-material-audit: read-only material list for the pyRevit Agent Runtime.

Submit with the pyrevit MCP tool run_query (or `pyrevit agent run <this file> --mode=query`).
IronPython 2.7 compatible: no f-strings, no type hints, no print kwargs.
The script changes nothing and writes no files. It sets `result` to a JSON-safe dict:

  {prefix, model, revit_year, timestamp, path, matched,
   materials: [{id, name, shading: {r, g, b} or None,
                shading_from_render_appearance: bool, transparency: int,
                surface_foreground: {pattern, pattern_id, color: {r, g, b} or None},
                surface_background: {pattern, pattern_id, color: {r, g, b} or None},
                cut_foreground: {pattern, pattern_id, color} or None,
                cut_background: {pattern, pattern_id, color} or None}],
   used_in_type_structure: [int, ...], used_in_family: [int, ...],
   type_structure_checked: {floor_types, wall_types, roof_types, ceiling_types,
                            family_symbols},
   not_checked: [str, ...]}

Optional inputs (dict): {"prefix": "Floor Finish"} (required, case-insensitive).
The unused check is scoped on purpose: it checks compound-structure layers of
floor, wall, roof and ceiling types first, then material parameters of family
types. It does NOT scan the full model. `not_checked` lists what it skipped,
so the answer to "which materials are unused" stays honest about its scope.
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

NOT_CHECKED = [
    "materials assigned directly to model elements (element material parameters)",
    "painted faces (Paint tool)",
    "materials in linked models",
    "materials used only inside in-place families",
    "materials used only by appearance or material assets",
]


def eid(element_id):
    """ElementId -> int. Revit 2024+ has .Value; 2023 and older only .IntegerValue."""
    if hasattr(element_id, "Value"):
        return int(element_id.Value)
    return int(element_id.IntegerValue)


IRONPYTHON = sys.platform == "cli"


def jsonable(value):
    """Make non-ASCII text survive the runtime's json.dumps on IronPython 2.7.

    IronPython's json encoder decodes every non-ASCII str as UTF-8 bytes and fails
    on names like 'Cafe' with an accent (ResultSerializationError). Handing it the
    UTF-8 bytes as latin-1 code points makes that decode return the real text.
    Tested live on Revit 2026 / IronPython 2.7.12. CPython needs no change.
    See am-model-health/scripts/model_health.py for the reason.
    """
    if isinstance(value, dict):
        return dict((jsonable(k), jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if IRONPYTHON and isinstance(value, basestring):  # noqa: F821
        if any(ord(c) > 127 for c in value):
            return value.encode("utf-8").decode("latin-1")
    return value


def rgb(color):
    """DB.Color -> {"r","g","b"} ints. None stays None."""
    if color is None:
        return None
    try:
        return {"r": int(color.Red), "g": int(color.Green), "b": int(color.Blue)}
    except Exception:
        return None


def pattern_entry(pattern_id, pattern_color):
    """One pattern slot: {"pattern", "pattern_id", "color"}.

    The color is None when the material has no pattern: the stored color of
    an empty slot means nothing. The pattern name comes from the
    FillPatternElement; "<none>" when the id is not valid.
    """
    pid = eid(pattern_id) if pattern_id is not None else -1
    if pid <= 0:
        return {"pattern": "<none>", "pattern_id": -1, "color": None}
    name = "<none>"
    try:
        element = doc.GetElement(pattern_id)  # noqa: F821
        if element is not None:
            name = element.Name
    except Exception:
        pass
    return {"pattern": name, "pattern_id": pid, "color": rgb(pattern_color)}


def cut_entry(pattern_id, pattern_color):
    """One cut-pattern slot, or None when the material has no cut pattern."""
    pid = eid(pattern_id) if pattern_id is not None else -1
    if pid <= 0:
        return None
    return pattern_entry(pattern_id, pattern_color)


def safe_name(element):
    try:
        return element.Name
    except Exception:
        return "(no name)"


def safe_shading(material):
    """Shading color (Graphics color) of a material, or None when unreadable."""
    try:
        return rgb(material.Color)
    except Exception:
        return None


def safe_flag(material, name, default=False):
    try:
        return bool(getattr(material, name))
    except Exception:
        return default


def safe_int(material, name, default=None):
    try:
        return int(getattr(material, name))
    except Exception:
        return default


def collect_materials(prefix):
    """Materials whose name starts with prefix (case-insensitive)."""
    found = []
    needle = prefix.lower()
    for mat in DB.FilteredElementCollector(doc).OfClass(DB.Material):  # noqa: F821
        name = safe_name(mat)
        if not name.lower().startswith(needle):
            continue
        found.append({
            "id": eid(mat.Id),
            "name": name,
            "shading": safe_shading(mat),
            "shading_from_render_appearance": safe_flag(mat, "UseRenderAppearanceForShading"),
            "transparency": safe_int(mat, "Transparency"),
            "surface_foreground": pattern_entry(mat.SurfaceForegroundPatternId,
                                                mat.SurfaceForegroundPatternColor),
            "surface_background": pattern_entry(mat.SurfaceBackgroundPatternId,
                                                mat.SurfaceBackgroundPatternColor),
            "cut_foreground": cut_entry(mat.CutForegroundPatternId,
                                        mat.CutForegroundPatternColor),
            "cut_background": cut_entry(mat.CutBackgroundPatternId,
                                        mat.CutBackgroundPatternColor),
        })
    found.sort(key=lambda m: m["name"].lower())
    return found


def structure_material_ids():
    """Material ids in compound-structure layers of floor/wall/roof/ceiling types.

    Returns (ids, counts). A type without a compound structure adds nothing.
    """
    ids = set()
    counts = {}
    for cls, key in ((DB.FloorType, "floor_types"), (DB.WallType, "wall_types"),
                     (DB.RoofType, "roof_types"), (DB.CeilingType, "ceiling_types")):
        n = 0
        for t in DB.FilteredElementCollector(doc).OfClass(cls):  # noqa: F821
            n += 1
            try:
                cs = t.GetCompoundStructure()
            except Exception:
                cs = None
            if cs is None:
                continue
            try:
                layers = cs.GetLayers()
            except Exception:
                continue
            for layer in layers:
                try:
                    mid = layer.MaterialId
                except Exception:
                    continue
                if mid is not None and eid(mid) > 0:
                    ids.add(eid(mid))
        counts[key] = n
    return ids, counts


def family_material_ids():
    """Material ids in material parameters of family types (FamilySymbol).

    Returns (ids, symbol_count). A family type parameter of type Material
    holds the material the family uses for that part.
    """
    ids = set()
    n = 0
    for sym in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).WhereElementIsElementType():  # noqa: F821
        n += 1
        try:
            params = sym.Parameters
        except Exception:
            continue
        for p in params:
            try:
                if p.Definition is None:
                    continue
                if p.Definition.ParameterType != DB.ParameterType.Material:
                    continue
                if not p.HasValue:
                    continue
                mid = p.AsElementId()
            except Exception:
                continue
            if mid is not None and eid(mid) > 0:
                ids.add(eid(mid))
    return ids, n


if doc is None or doc.IsFamilyDocument:  # noqa: F821
    result = {"error": "no_project_document",
              "message": "Open a Revit project (.rvt), not a family, then run again."}
elif not PREFIX:
    result = {"error": "no_prefix",
              "message": "Give a name prefix, for example \"Floor Finish\"."}
else:
    materials = collect_materials(PREFIX)
    used_type, checked = structure_material_ids()
    used_family, symbol_count = family_material_ids()
    checked["family_symbols"] = symbol_count
    result = {
        "prefix": PREFIX,
        "model": doc.Title,  # noqa: F821
        "revit_year": str(app.VersionNumber),  # noqa: F821
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "path": doc.PathName or "",  # noqa: F821
        "matched": len(materials),
        "materials": materials,
        "used_in_type_structure": sorted(used_type),
        "used_in_family": sorted(used_family),
        "type_structure_checked": checked,
        "not_checked": NOT_CHECKED,
    }
    result = jsonable(result)
    unused = len([m for m in materials
                  if m["id"] not in used_type and m["id"] not in used_family])
    print("am-material-audit: %d materials starting with %r, %d unused (scoped check)" % (
        len(materials), PREFIX, unused))

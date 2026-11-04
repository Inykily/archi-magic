# -*- coding: utf-8 -*-
"""am-fill-standards: read-only filled region and fill pattern list for the
pyRevit Agent Runtime.

Submit with the pyrevit MCP tool run_query (or `pyrevit agent run <this file>
--mode=query`). IronPython 2.7 compatible: no f-strings, no type hints, no
print kwargs. The script changes nothing and writes no files. It sets
`result` to a JSON-safe dict:

  {model, revit_year, timestamp, path,
   reference_view: {id, name, type} or None,
   drafting_views: [{id, name, type, region_count}],
   types: [{id, name, masking: bool or None,
            fg: {pattern, pattern_id, color: {r, g, b} or None},
            bg: {pattern, pattern_id, color},
            line_weight: int or None,
            drawing_uses: int, reference_uses: int}],
   patterns: [{id, name, target: "Drafting" or "Model" or None}],
   swatches: [{id, type_id, type_name, cx, cy}],
   labels: [{id, text, cx, cy, text_type_id}]}

Optional inputs (dict): {"reference_view_name": "<name>"} or
{"reference_view_id": 123}. The reference view is the drafting view (or
legend view) that holds one swatch per type with a text label under it.
When no reference view is given, the script lists every drafting and
legend view with its region count, and every instance counts as a
drawing use: pick the view, then run again with its name.

Use split: an instance in the reference view counts as a reference use.
An instance anywhere else counts as a drawing use. A type with no
instances at all is unused. A FilledRegion in a legend or reference view
still counts as a use: that is why the split exists.

Non-ASCII names: a pattern name can hold a degree sign, which breaks
IronPython result JSON (see issue #76). The jsonable step below smuggles
it through as UTF-8 bytes read back as latin-1, the same method as
am-model-health and am-material-audit. The compute step needs no change.
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


def eid(element_id):
    """ElementId -> int. Revit 2024+ has .Value; 2023 and older only .IntegerValue."""
    if hasattr(element_id, "Value"):
        return int(element_id.Value)
    return int(element_id.IntegerValue)


IRONPYTHON = sys.platform == "cli"


def jsonable(value):
    """Make non-ASCII text survive the runtime's json.dumps on IronPython 2.7.

    IronPython's json encoder decodes every non-ASCII str as UTF-8 bytes and fails
    on names like a pattern name with a degree sign (ResultSerializationError).
    Handing it the UTF-8 bytes as latin-1 code points makes that decode return
    the real text. Tested live on Revit 2026 / IronPython 2.7.12. CPython needs
    no change. See am-model-health/scripts/model_health.py for the reason.
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


def safe_name(element):
    try:
        return element.Name
    except Exception:
        return "(no name)"


def safe_flag(element, name, default=None):
    try:
        return bool(getattr(element, name))
    except Exception:
        return default


def safe_int(element, name, default=None):
    try:
        return int(getattr(element, name))
    except Exception:
        return default


def pattern_entry(pattern_id, pattern_color):
    """One pattern slot: {"pattern", "pattern_id", "color"}.

    The color is None when the type has no pattern: the stored color of
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


def find_reference_view():
    """The reference view from inputs, or None when not given or not found.

    Matches a drafting or legend view by id first, then by exact name
    (case-insensitive, templates skipped). A view of another kind never
    counts: only drafting and legend views hold swatches.
    """
    wanted_id = INPUTS.get("reference_view_id")
    wanted_name = INPUTS.get("reference_view_name")
    if wanted_name is not None:
        wanted_name = wanted_name.strip().lower()
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):  # noqa: F821
        if v.IsTemplate:
            continue
        if str(v.ViewType) not in ("DraftingView", "Legend"):
            continue
        if wanted_id is not None and eid(v.Id) == int(wanted_id):
            return v
        if wanted_name and v.Name.strip().lower() == wanted_name:
            return v
    return None


def view_rows():
    """Every drafting and legend view with its FilledRegion count."""
    rows = []
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):  # noqa: F821
        if v.IsTemplate:
            continue
        if str(v.ViewType) not in ("DraftingView", "Legend"):
            continue
        n = 0
        try:
            n = DB.FilteredElementCollector(doc, v.Id).OfClass(  # noqa: F821
                DB.FilledRegion).GetElementCount()
        except Exception:
            n = 0
        rows.append({"id": eid(v.Id), "name": v.Name,
                     "type": str(v.ViewType), "region_count": n})
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def center_in_view(element, view):
    """Bounding box center (cx, cy) in feet, or (None, None).

    View-specific elements report a box in their owner view. A TextNote
    with no box reports no center: the pairing step leaves it unpaired
    for the user to resolve by hand, instead of guessing.
    """
    try:
        box = element.get_BoundingBox(view)
    except Exception:
        box = None
    if box is None:
        return None, None
    try:
        cx = (box.Min.X + box.Max.X) / 2.0
        cy = (box.Min.Y + box.Max.Y) / 2.0
        return cx, cy
    except Exception:
        return None, None


def collect_types(ref_view_id):
    """Filled region types with pattern slots, Masking, and use counts."""
    types = []
    by_id = {}
    for t in DB.FilteredElementCollector(doc).OfClass(  # noqa: F821
            DB.FilledRegionType):
        row = {
            "id": eid(t.Id),
            "name": safe_name(t),
            "masking": safe_flag(t, "IsMasking", None),
            "fg": pattern_entry(t.ForegroundPatternId,
                                t.ForegroundPatternColor),
            "bg": pattern_entry(t.BackgroundPatternId,
                                t.BackgroundPatternColor),
            "line_weight": safe_int(t, "LineWeight", None),
            "drawing_uses": 0,
            "reference_uses": 0,
        }
        types.append(row)
        by_id[row["id"]] = row
    for fr in DB.FilteredElementCollector(doc).OfClass(DB.FilledRegion):  # noqa: F821
        try:
            tid = eid(fr.GetTypeId())
        except Exception:
            continue
        row = by_id.get(tid)
        if row is None:
            continue
        try:
            owner = eid(fr.OwnerViewId)
        except Exception:
            owner = -1
        if ref_view_id is not None and owner == ref_view_id:
            row["reference_uses"] += 1
        else:
            row["drawing_uses"] += 1
    types.sort(key=lambda r: r["name"].lower())
    return types


def collect_patterns():
    """Fill pattern elements: name and Drafting/Model target."""
    patterns = []
    for p in DB.FilteredElementCollector(doc).OfClass(  # noqa: F821
            DB.FillPatternElement):
        target = None
        try:
            target = str(p.GetFillPattern().Target)
        except Exception:
            target = None
        patterns.append({"id": eid(p.Id), "name": safe_name(p),
                         "target": target})
    patterns.sort(key=lambda r: r["name"].lower())
    return patterns


def collect_reference_contents(ref_view):
    """Swatches and labels of the reference view, with centers."""
    swatches = []
    labels = []
    if ref_view is None:
        return swatches, labels
    for fr in DB.FilteredElementCollector(doc, ref_view.Id).OfClass(  # noqa: F821
            DB.FilledRegion):
        try:
            tid = eid(fr.GetTypeId())
            tname = safe_name(doc.GetElement(fr.GetTypeId()))  # noqa: F821
        except Exception:
            tid = -1
            tname = None
        cx, cy = center_in_view(fr, ref_view)
        swatches.append({"id": eid(fr.Id), "type_id": tid,
                         "type_name": tname, "cx": cx, "cy": cy})
    for tn in DB.FilteredElementCollector(doc, ref_view.Id).OfClass(  # noqa: F821
            DB.TextNote):
        try:
            text = tn.Text
        except Exception:
            text = ""
        try:
            text_type_id = eid(tn.GetTypeId())
        except Exception:
            text_type_id = -1
        cx, cy = center_in_view(tn, ref_view)
        labels.append({"id": eid(tn.Id), "text": text, "cx": cx, "cy": cy,
                       "text_type_id": text_type_id})
    return swatches, labels


if doc is None or doc.IsFamilyDocument:  # noqa: F821
    result = {"error": "no_project_document",
              "message": "Open a Revit project (.rvt), not a family, then run again."}
else:
    ref_view = find_reference_view()
    if (INPUTS.get("reference_view_name") or INPUTS.get("reference_view_id")) \
            and ref_view is None:
        result = {"error": "no_reference_view",
                  "message": "No drafting or legend view matches that name or id. "
                             "Run again with no reference view to list them."}
    else:
        ref_id = eid(ref_view.Id) if ref_view is not None else None
        types = collect_types(ref_id)
        swatches, labels = collect_reference_contents(ref_view)
        result = {
            "model": doc.Title,  # noqa: F821
            "revit_year": str(app.VersionNumber),  # noqa: F821
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "path": doc.PathName or "",  # noqa: F821
            "reference_view": ({"id": ref_id, "name": ref_view.Name,
                                "type": str(ref_view.ViewType)}
                               if ref_view is not None else None),
            "drafting_views": view_rows(),
            "types": types,
            "patterns": collect_patterns(),
            "swatches": swatches,
            "labels": labels,
        }
        result = jsonable(result)
        print("am-fill-standards: %d types, %d swatches, %d labels" % (
            len(types), len(swatches), len(labels)))

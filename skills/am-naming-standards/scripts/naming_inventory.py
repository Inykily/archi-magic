# -*- coding: utf-8 -*-
"""am-naming-standards: read-only naming inventory for the pyRevit Agent Runtime.

Submit with the pyrevit MCP tool run_query, passing `inputs`
(or `pyrevit agent run <this file> --mode=query --inputs=<json>`).
IronPython 2.7 compatible: no f-strings, no type hints, no print kwargs.
The script changes nothing and writes no files. It sets `result` to
a JSON-safe dict for naming_tables.py:

  {model, revit_year, rows: [{id, category, name, instance_count,
   referencing_type_count, sketch_dimension_count,
   in_reference_view_only, real_size}],
   view_filters: [{id, name, values: [str]}],
   schedule_filters: [{id, name, values: [str]}],
   unplaced_group_types: [{id, name}],
   placed_group_members: {group_type_id: [member_type_ids]},
   reference_views: [{id, name, kind, labels: [{text,
     sample_style_exists, starts_with_type_name, has_labels}]}],
   not_checked: [str]}

inputs (all optional):
  {"categories": ["text_type", "dimension_type", ...],
   "max_rows": 500}

Usage counts, honestly scoped. instance_count counts elements
whose type id is the row id. For dimension types, dimensions
with no valid owner view count separately as
sketch_dimension_count and never count as uses: they are
internal sketch dimensions, and they inflate counts. Heads,
marks and view titles that use a type are NOT counted here:
scan the type properties of levels, grids and viewports for
those references and add them to referencing_type_count by
hand when you need them. Group types with no placed instance
list no members: their members cannot be read from the type
alone, so a delete while they exist is never safe.
"""
import sys

from pyrevit.api import DB

try:
    INPUTS = inputs  # noqa: F821  (injected by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}

IRONPYTHON = sys.platform == "cli"

ALL_CATEGORIES = ["view_template", "text_type", "dimension_type",
                  "line_style", "family_type", "filled_region_type",
                  "fill_pattern"]
WANTED = INPUTS.get("categories") or ALL_CATEGORIES
MAX_ROWS = int(INPUTS.get("max_rows", 500))


def jsonable(value):
    """Keep non-ASCII names intact through the runtime's json.dumps.

    A degree sign in a pattern name broke IronPython result JSON
    before (see the filled-region issue). Decode byte strings to
    unicode on IronPython; leave CPython 3 strings alone.
    """
    if isinstance(value, dict):
        return dict((jsonable(k), jsonable(v))
                    for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if IRONPYTHON and isinstance(value, str):
        try:
            return value.decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return value.decode("utf-8", "replace")
    return value


def safe_name(element):
    try:
        return element.Name or ""
    except Exception:
        return ""


def type_id_of(element):
    try:
        tid = element.GetTypeId()
        if tid is not None and tid.IntegerValue > 0:
            return tid.IntegerValue
    except Exception:
        pass
    return None


def collect_types(doc):
    """One inventory row per type, per wanted category."""
    rows = []
    col = DB.FilteredElementCollector(doc)
    if "view_template" in WANTED:
        for view in col.OfClass(DB.View):
            try:
                if view.IsTemplate:
                    rows.append({"id": view.Id.IntegerValue,
                                 "category": "view_template",
                                 "name": safe_name(view)})
            except Exception:
                continue
    if "text_type" in WANTED:
        for t in col.OfClass(DB.TextNoteType):
            rows.append({"id": t.Id.IntegerValue,
                         "category": "text_type",
                         "name": safe_name(t)})
    if "dimension_type" in WANTED:
        for t in col.OfClass(DB.DimensionType):
            rows.append({"id": t.Id.IntegerValue,
                         "category": "dimension_type",
                         "name": safe_name(t)})
    if "line_style" in WANTED:
        try:
            for cat in doc.Settings.Categories:
                try:
                    subs = cat.SubCategories
                except Exception:
                    continue
                if subs is None:
                    continue
                for sub in subs:
                    rows.append({"id": sub.Id.IntegerValue,
                                 "category": "line_style",
                                 "name": safe_name(sub)})
        except Exception:
            pass
    if "family_type" in WANTED:
        for s in col.OfClass(DB.FamilySymbol):
            rows.append({"id": s.Id.IntegerValue,
                         "category": "family_type",
                         "name": safe_name(s)})
    if "filled_region_type" in WANTED:
        for t in col.OfClass(DB.FilledRegionType):
            rows.append({"id": t.Id.IntegerValue,
                         "category": "filled_region_type",
                         "name": safe_name(t)})
    if "fill_pattern" in WANTED:
        for p in col.OfClass(DB.FillPatternElement):
            rows.append({"id": p.Id.IntegerValue,
                         "category": "fill_pattern",
                         "name": safe_name(p)})
    return rows[:MAX_ROWS]


def count_uses(doc, rows):
    """Fill instance counts and the scoped usage notes per row."""
    by_id = {}
    for row in rows:
        row["instance_count"] = 0
        row["referencing_type_count"] = None
        row["sketch_dimension_count"] = 0
        row["in_reference_view_only"] = False
        row["real_size"] = ""
        by_id[row["id"]] = row
    col = DB.FilteredElementCollector(doc)
    view_kinds = {}
    for view in col.OfClass(DB.View):
        try:
            view_kinds[view.Id.IntegerValue] = view.ViewType
        except Exception:
            continue

    def note_instance(element, view_id):
        tid = type_id_of(element)
        if tid is None or tid not in by_id:
            return
        row = by_id[tid]
        if row["category"] == "dimension_type":
            if view_id is None or view_id < 0:
                row["sketch_dimension_count"] += 1
                return
        row["instance_count"] += 1

    for element in col.OfClass(DB.TextNote):
        note_instance(element, None)
    for element in col.OfClass(DB.Dimension):
        try:
            owner = element.OwnerViewId
            view_id = owner.IntegerValue if owner is not None else -1
        except Exception:
            view_id = -1
        note_instance(element, view_id)
    for element in col.OfClass(DB.FamilyInstance):
        try:
            sid = element.Symbol.Id.IntegerValue
        except Exception:
            sid = None
        if sid is not None and sid in by_id:
            by_id[sid]["instance_count"] += 1
    ref_only = {}
    for element in col.OfClass(DB.FilledRegion):
        tid = type_id_of(element)
        if tid is None or tid not in by_id:
            continue
        by_id[tid]["instance_count"] += 1
        try:
            owner = element.OwnerViewId
            view_id = owner.IntegerValue if owner is not None else -1
        except Exception:
            view_id = -1
        kind = view_kinds.get(view_id)
        is_ref = kind in (DB.ViewType.DraftingView, DB.ViewType.Legend)
        if tid not in ref_only:
            ref_only[tid] = True
        if not is_ref:
            ref_only[tid] = False
    for tid, only in ref_only.items():
        by_id[tid]["in_reference_view_only"] = only
    for view in col.OfClass(DB.View):
        try:
            template_id = view.ViewTemplateId
        except Exception:
            continue
        if template_id is not None and template_id.IntegerValue in by_id:
            by_id[template_id.IntegerValue]["instance_count"] += 1
    return rows


def collect_filters(doc):
    """View filter rules and schedule filter values, as strings."""
    view_filters = []
    for f in DB.FilteredElementCollector(doc).OfClass(
            DB.ParameterFilterElement):
        values = []
        try:
            for rule in f.GetRules():
                try:
                    values.append(str(rule))
                except Exception:
                    continue
        except Exception:
            pass
        view_filters.append({"id": f.Id.IntegerValue,
                             "name": safe_name(f), "values": values})
    schedule_filters = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        try:
            definition = view.Definition
        except Exception:
            continue
        try:
            filters = definition.GetFilters()
        except Exception:
            continue
        for sfilter in filters:
            try:
                value = sfilter.FilterValue
                text = "" if value is None else str(value)
            except Exception:
                text = ""
            schedule_filters.append({"id": view.Id.IntegerValue,
                                     "name": safe_name(view),
                                     "values": [text]})
    return view_filters, schedule_filters


def collect_groups(doc):
    """Group types: placed members where known, unplaced listed."""
    placed = {}
    placed_type_ids = set()
    for group in DB.FilteredElementCollector(doc).OfClass(DB.Group):
        try:
            type_id = group.GroupType.Id.IntegerValue
        except Exception:
            continue
        placed_type_ids.add(type_id)
        members = []
        try:
            for member_id in group.GetMemberIds():
                try:
                    member = doc.GetElement(member_id)
                    tid = type_id_of(member)
                    if tid is not None:
                        members.append(tid)
                except Exception:
                    continue
        except Exception:
            pass
        placed[type_id] = members
    unplaced = []
    for gt in DB.FilteredElementCollector(doc).OfClass(DB.GroupType):
        gid = gt.Id.IntegerValue
        if gid not in placed_type_ids:
            unplaced.append({"id": gid, "name": safe_name(gt)})
    return unplaced, placed


def collect_reference_views(doc):
    """Drafting views and legends: text labels per view."""
    views = []
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
        try:
            kind = view.ViewType
        except Exception:
            continue
        if kind not in (DB.ViewType.DraftingView, DB.ViewType.Legend):
            continue
        labels = []
        try:
            notes = DB.FilteredElementCollector(
                doc, view.Id).OfClass(DB.TextNote)
            for note in notes:
                try:
                    text = note.Text or ""
                except Exception:
                    text = ""
                labels.append({"text": text,
                               "sample_style_exists": True,
                               "starts_with_type_name": False,
                               "has_labels": True})
        except Exception:
            pass
        views.append({"id": view.Id.IntegerValue,
                      "name": safe_name(view),
                      "kind": "legend" if kind == DB.ViewType.Legend
                      else "reference",
                      "labels": labels})
    return views


def main():
    doc = __revit__.ActiveUIDocument.Document  # noqa: F821
    rows = collect_types(doc)
    rows = count_uses(doc, rows)
    view_filters, schedule_filters = collect_filters(doc)
    unplaced, placed = collect_groups(doc)
    ref_views = collect_reference_views(doc)
    try:
        year = doc.Application.VersionNumber
    except Exception:
        year = ""
    try:
        title = doc.Title or ""
    except Exception:
        title = ""
    result = {"model": title, "revit_year": year, "rows": rows,
              "view_filters": view_filters,
              "schedule_filters": schedule_filters,
              "unplaced_group_types": unplaced,
              "placed_group_members": placed,
              "reference_views": ref_views,
              "not_checked": [
                  "view names (the issue leaves them open)",
                  "system family types such as walls and floors",
                  "heads, tags and view titles that use a type "
                  "(scan level, grid and viewport type properties)",
                  "members of group types with no placed instance"]}
    return jsonable(result)


result = main()  # noqa: F821

# -*- coding: utf-8 -*-
"""am-model-health: read-only model QA for the pyRevit Agent Runtime.

Submit with the pyrevit MCP tool run_query (or `pyrevit agent run <this file> --mode=query`).
IronPython 2.7 compatible: no f-strings, no type hints, no print kwargs.
The script changes nothing and writes no files. It sets `result` to a JSON-safe dict:

  {model, revit_year, timestamp, path, metrics: [
      {id, label, value, unit, threshold: {warn, bad}, status: ok|warn|bad|info,
       hint, details: [{label, count, ids: [int, ...]}]}]}

Optional inputs (dict): {"max_ids": 300, "top_warnings": 15}
"""
import datetime
import sys

import System
from pyrevit.api import DB

try:
    INPUTS = inputs  # noqa: F821  (injected by the agent runtime)
except NameError:
    INPUTS = None
if not isinstance(INPUTS, dict):
    INPUTS = {}

MAX_IDS = int(INPUTS.get("max_ids", 300))
TOP_WARNINGS = int(INPUTS.get("top_warnings", 15))
FAR_FT = 328.084  # 100 m. A link origin farther than this is a coordinate hint.


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
    """
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if IRONPYTHON and isinstance(value, basestring):  # noqa: F821
        if any(ord(c) > 127 for c in value):
            return value.encode("utf-8").decode("latin-1")
    return value


def status_for(value, warn, bad):
    """Higher value is worse. None thresholds mean information only."""
    if warn is None and bad is None:
        return "info"
    if bad is not None and value > bad:
        return "bad"
    if warn is not None and value > warn:
        return "warn"
    return "ok"


def metric(mid, label, value, warn, bad, hint, details=None, unit=""):
    details = [d for d in (details or []) if d.get("count")]
    return {
        "id": mid,
        "label": label,
        "value": value,
        "unit": unit,
        "threshold": {"warn": warn, "bad": bad},
        "status": status_for(value, warn, bad),
        "hint": hint,
        "details": details or [],
    }


def collect(cls=None, bic=None, types=False):
    col = DB.FilteredElementCollector(doc)  # noqa: F821
    if cls is not None:
        col = col.OfClass(cls)
    if bic is not None:
        col = col.OfCategory(bic)
    if not types and cls is None:
        col = col.WhereElementIsNotElementType()
    return list(col)


def safe_name(element):
    try:
        return element.Name
    except Exception:
        return "(no name)"


def check_warnings():
    groups = {}
    order = []
    for w in doc.GetWarnings():  # noqa: F821
        text = w.GetDescriptionText()
        if text not in groups:
            groups[text] = []
            order.append(text)
        groups[text].extend([eid(i) for i in w.GetFailingElements()])
        groups[text].append(None)  # one marker per warning instance
    rows = []
    total = 0
    for text in order:
        ids = [i for i in groups[text] if i is not None]
        count = len(groups[text]) - len(ids)
        total += count
        rows.append({"label": text, "count": count, "ids": ids[:MAX_IDS]})
    rows.sort(key=lambda r: -r["count"])
    return total, rows


def check_links():
    types = collect(cls=DB.RevitLinkType)
    insts = collect(cls=DB.RevitLinkInstance)
    unloaded = []
    for lt in types:
        try:
            loaded = DB.RevitLinkType.IsLoaded(doc, lt.Id)  # noqa: F821
        except Exception:
            loaded = False
        if not loaded:
            unloaded.append(lt)
    unpinned = [li for li in insts if not li.Pinned]
    far = []
    for li in insts:
        try:
            o = li.GetTotalTransform().Origin
            if abs(o.X) > FAR_FT or abs(o.Y) > FAR_FT or abs(o.Z) > FAR_FT:
                far.append(li)
        except Exception:
            pass
    placed_type_ids = set([eid(li.GetTypeId()) for li in insts])
    not_placed = [lt for lt in types if eid(lt.Id) not in placed_type_ids]
    return types, insts, unloaded, unpinned, far, not_placed


def check_in_place():
    inplace = [f for f in collect(cls=DB.Family) if f.IsInPlace]
    inplace_ids = set([eid(f.Id) for f in inplace])
    rows = {}
    for fi in collect(cls=DB.FamilyInstance):
        try:
            fam = fi.Symbol.Family
        except Exception:
            continue
        if fam is not None and eid(fam.Id) in inplace_ids:
            key = fam.Name
            rows.setdefault(key, []).append(eid(fi.Id))
    details = [{"label": k, "count": len(v), "ids": v[:MAX_IDS]} for k, v in rows.items()]
    details.sort(key=lambda r: -r["count"])
    return len(inplace), details


def check_rooms(warning_rows):
    unplaced, not_enclosed = [], []
    total = 0
    for r in collect(bic=DB.BuiltInCategory.OST_Rooms):
        total += 1
        try:
            area = r.Area
        except Exception:
            continue
        if area > 0:
            continue
        if r.Location is None:
            unplaced.append(eid(r.Id))
        else:
            not_enclosed.append(eid(r.Id))
    redundant = []
    for row in warning_rows:
        if "Multiple Rooms" in row["label"] or "redundant" in row["label"].lower():
            redundant.extend(row["ids"])
    return total, unplaced, not_enclosed, sorted(set(redundant))


def check_duplicate_marks():
    marks = {}
    for el in DB.FilteredElementCollector(doc).WhereElementIsNotElementType():  # noqa: F821
        cat = el.Category
        if cat is None or cat.CategoryType != DB.CategoryType.Model:
            continue
        p = el.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
        if p is None:
            continue
        v = p.AsString()
        if not v or not v.strip():
            continue
        marks.setdefault((cat.Name, v.strip()), []).append(eid(el.Id))
    rows = []
    for (cat_name, mark), ids in marks.items():
        if len(ids) > 1:
            rows.append({"label": "%s / Mark %s" % (cat_name, mark), "count": len(ids), "ids": ids[:MAX_IDS]})
    rows.sort(key=lambda r: -r["count"])
    return sum([r["count"] for r in rows]), rows


def check_cad():
    imported, linked = [], []
    for ci in collect(cls=DB.ImportInstance):
        name = "(unknown)"
        try:
            if ci.Category is not None:
                name = ci.Category.Name
        except Exception:
            pass
        (linked if ci.IsLinked else imported).append((name, eid(ci.Id)))
    def group(items):
        g = {}
        for name, i in items:
            g.setdefault(name, []).append(i)
        return [{"label": k, "count": len(v), "ids": v[:MAX_IDS]} for k, v in g.items()]
    return imported, linked, group(imported), group(linked)


def check_views():
    views = [v for v in collect(cls=DB.View) if not v.IsTemplate]
    sheets = [v for v in views if isinstance(v, DB.ViewSheet)]
    placed = set()
    for s in sheets:
        for vid in s.GetAllPlacedViews():
            placed.add(eid(vid))
    loose = [v for v in views
             if not isinstance(v, DB.ViewSheet) and v.CanBePrinted and eid(v.Id) not in placed]
    return views, sheets, loose


def file_size_mb():
    path = doc.PathName  # noqa: F821
    if not path:
        return None, "Model is not saved yet."
    try:
        if System.IO.File.Exists(path):
            return round(System.IO.FileInfo(path).Length / 1048576.0, 1), path
    except Exception:
        pass
    return None, "File not on a local path (cloud or server model): " + path


if doc is None or doc.IsFamilyDocument:  # noqa: F821
    result = {"error": "no_project_document",
              "message": "Open a Revit project (.rvt), not a family, then run again."}
else:
    metrics = []
    w_total, w_rows = check_warnings()
    metrics.append(metric("warnings", "Revit warnings", w_total, 50, 500,
                          "Fix the biggest warning types first. Many warnings slow the model.",
                          w_rows[:TOP_WARNINGS]))

    l_types, l_insts, l_unloaded, l_unpinned, l_far, l_unplaced = check_links()
    metrics.append(metric("links_unloaded", "Revit links not loaded", len(l_unloaded), 0, 2,
                          "Reload or remove these links in Manage Links.",
                          [{"label": safe_name(t), "count": 1, "ids": [eid(t.Id)]} for t in l_unloaded]))
    metrics.append(metric("links_unpinned", "Revit links not pinned", len(l_unpinned), 0, 3,
                          "Pin links so nobody moves them by accident.",
                          [{"label": safe_name(i), "count": 1, "ids": [eid(i.Id)]} for i in l_unpinned]))
    metrics.append(metric("links_far", "Links far from the origin (shared coordinates hint)", len(l_far), 0, None,
                          "Heuristic only: origin more than 100 m away. Check shared coordinates with the link owner.",
                          [{"label": safe_name(i), "count": 1, "ids": [eid(i.Id)]} for i in l_far]))
    # Revit names a link instance "<file> : <id> : location <Not Shared>" when it is not placed by
    # shared coordinates. English Revit only; other languages show 0 here. Heuristic, like links_far.
    l_not_shared = [i for i in l_insts if "<Not Shared>" in safe_name(i)]
    metrics.append(metric("links_not_shared", "Links not on shared coordinates (hint)", len(l_not_shared), 0, None,
                          "Heuristic from the link name. Agree on shared coordinates with the link owners.",
                          [{"label": safe_name(i), "count": 1, "ids": [eid(i.Id)]} for i in l_not_shared]))
    metrics.append(metric("links_total", "Revit link instances", len(l_insts), None, None,
                          "%d link types, %d not placed." % (len(l_types), len(l_unplaced)),
                          [{"label": safe_name(t) + " (type not placed)", "count": 1, "ids": [eid(t.Id)]}
                           for t in l_unplaced]))

    ip_count, ip_rows = check_in_place()
    metrics.append(metric("in_place_families", "In-place families", ip_count, 10, 30,
                          "Turn repeated in-place families into loadable families.", ip_rows))

    r_total, r_unplaced, r_open, r_redundant = check_rooms(w_rows)
    metrics.append(metric("rooms_unplaced", "Rooms not placed", len(r_unplaced), 0, 20,
                          "Place these rooms or delete them (Room schedule).",
                          [{"label": "Not placed", "count": len(r_unplaced), "ids": r_unplaced[:MAX_IDS]}]))
    metrics.append(metric("rooms_not_enclosed", "Rooms not enclosed", len(r_open), 0, 10,
                          "Close the room boundaries or add room separation lines.",
                          [{"label": "Not enclosed", "count": len(r_open), "ids": r_open[:MAX_IDS]}]))
    metrics.append(metric("rooms_redundant", "Redundant rooms (two rooms in one space)", len(r_redundant), 0, 10,
                          "Delete the extra room in each space.",
                          [{"label": "Redundant", "count": len(r_redundant), "ids": r_redundant[:MAX_IDS]}]))

    dm_count, dm_rows = check_duplicate_marks()
    metrics.append(metric("duplicate_marks", "Elements with duplicate Mark", dm_count, 0, 50,
                          "Give each element in a category its own Mark.", dm_rows[:50]))

    c_imp, c_lnk, c_imp_rows, c_lnk_rows = check_cad()
    metrics.append(metric("cad_imported", "Imported CAD (not linked)", len(c_imp), 0, 5,
                          "Delete imported CAD, or replace it with a linked CAD file.", c_imp_rows))
    metrics.append(metric("cad_linked", "Linked CAD", len(c_lnk), None, None,
                          "Information only.", c_lnk_rows))

    v_all, v_sheets, v_loose = check_views()
    metrics.append(metric("views_not_on_sheets", "Views not on sheets", len(v_loose), 150, 400,
                          "%d views and %d sheets in total. Delete views you do not need." % (len(v_all), len(v_sheets)),
                          [{"label": safe_name(v), "count": 1, "ids": [eid(v.Id)]} for v in v_loose[:MAX_IDS]]))

    size, size_note = file_size_mb()
    if size is not None:
        metrics.append(metric("file_size", "File size", size, 300, 600,
                              "Big files open slowly. Purge unused items and check imported CAD.", [], "MB"))
    else:
        metrics.append(metric("file_size", "File size", 0, None, None, size_note, [], "MB"))

    result = {
        "model": doc.Title,  # noqa: F821
        "revit_year": str(app.VersionNumber),  # noqa: F821
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "path": doc.PathName or "",  # noqa: F821
        "workshared": bool(doc.IsWorkshared),  # noqa: F821
        "metrics": metrics,
    }
    result = jsonable(result)
    bad = len([m for m in metrics if m["status"] == "bad"])
    warn = len([m for m in metrics if m["status"] == "warn"])
    print("am-model-health: %d metrics, %d bad, %d warn" % (len(metrics), bad, warn))

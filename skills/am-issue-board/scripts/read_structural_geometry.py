# -*- coding: utf-8 -*-
"""Read reviewed host and linked element inventories through pyRevit run_query."""
import json
import math
import re

from System import Int64
from System.Diagnostics import Stopwatch
from pyrevit.api import DB

import issue_board as ib


class ReadError(ValueError):
    pass


def element_id(raw):
    if not re.match(r"^[1-9][0-9]{0,18}\Z", str(raw)) or int(raw) > 2**63 - 1:
        raise ReadError("Expected positive decimal element IDs.")
    return DB.ElementId(Int64(int(raw)))


def selected_ids(values):
    if not isinstance(values, list) or len(values) > 300:
        raise ReadError("Supply at most 300 reviewed IDs per model.")
    ids = [element_id(value) for value in values]
    if len({identifier.Value for identifier in ids}) != len(ids):
        raise ReadError("A model inventory has duplicate IDs.")
    return ids


def sampled_bounds(geometry, frame, budget, clock):
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    vertices = [0]

    def account(count):
        budget[0] += count
        if budget[0] > 1000000 or clock.ElapsedMilliseconds >= 10000:
            raise ReadError("Geometry exceeded the query budget. Use smaller inventories.")

    def visit(items, transform, depth):
        if depth > 8:
            raise ReadError("Geometry exceeds the supported nesting.")
        for item in items:
            account(1)
            if isinstance(item, DB.GeometryInstance):
                visit(item.GetSymbolGeometry(), transform.Multiply(item.Transform), depth + 1)
            elif isinstance(item, DB.Mesh):
                raise ReadError("The selected geometry contains a mesh without solid evidence.")
            elif isinstance(item, DB.Solid) and item.Faces.Size and item.Volume > 0:
                for face in item.Faces:
                    account(1)
                    mesh = face.Triangulate()
                    account(mesh.Vertices.Count)
                    for vertex in mesh.Vertices:
                        if clock.ElapsedMilliseconds >= 10000:
                            raise ReadError("Geometry exceeded the query budget. Use smaller inventories.")
                        p = transform.OfPoint(vertex)
                        for axis, value in enumerate((p.X, p.Y, p.Z)):
                            if math.isnan(value) or math.isinf(value) or abs(value) > 1e6:
                                raise ReadError("Geometry contains invalid or out-of-range points.")
                            low[axis] = min(low[axis], value)
                            high[axis] = max(high[axis], value)
                        vertices[0] += 1
                        if vertices[0] > 100000:
                            raise ReadError("One element exceeded the vertex limit.")

    if geometry is not None:
        visit(geometry, frame, 0)
    if not vertices[0] or any(not 0 < b - a <= 10000 for a, b in zip(low, high)):
        raise ReadError("An inventory element has no supported solid envelope.")
    return low, high


def read_inventory(document, ids, frame, budget, clock):
    categories = {
        int(DB.BuiltInCategory.OST_Columns): "column",
        int(DB.BuiltInCategory.OST_StructuralColumns): "column",
        int(DB.BuiltInCategory.OST_Walls): "wall",
        int(DB.BuiltInCategory.OST_Floors): "slab",
    }
    options = DB.Options()
    options.DetailLevel = DB.ViewDetailLevel.Fine
    options.IncludeNonVisibleObjects = False
    result = []
    for identifier in ids:
        if clock.ElapsedMilliseconds >= 10000:
            raise ReadError("Geometry exceeded the query budget. Use smaller inventories.")
        element = document.GetElement(identifier)
        if element is None or isinstance(element, DB.ElementType) or element.Category is None:
            raise ReadError("An inventory ID does not identify a supported element instance.")
        category = categories.get(element.Category.Id.Value)
        if category is None:
            raise ReadError("Use column, wall, or floor slab instances.")
        low, high = sampled_bounds(element.get_Geometry(options), frame, budget, clock)
        result.append({"id": str(identifier.Value), "uid": str(element.UniqueId),
                       "category": category, "min": low, "max": high})
    return sorted(result, key=lambda row: int(row["id"]))


def main():
    args = inputs if isinstance(inputs, dict) else {}  # noqa: F821
    host = doc  # noqa: F821
    if host is None or host.IsFamilyDocument:
        raise ReadError("Open the saved Revit project first.")
    scope = args.get("scope")
    if not isinstance(scope, (type(u""), str)):
        raise ReadError("Describe the reviewed phase, level and design scope.")
    if not scope.strip() or len(scope) > 160:
        raise ReadError("Describe the reviewed phase, level and design scope.")
    host_ids = selected_ids(args.get("host_ids"))
    link_ids = selected_ids(args.get("link_ids"))
    if not host_ids and not link_ids:
        raise ReadError("Supply at least one inventory element.")
    link = host.GetElement(element_id(args.get("link_instance_id")))
    if not isinstance(link, DB.RevitLinkInstance):
        raise ReadError("Select one structural link instance.")
    linked = link.GetLinkDocument()
    if linked is None:
        raise ReadError("The selected structural link is unloaded.")
    clock = Stopwatch.StartNew()
    budget = [0]
    payload = {
        "kind": "structural-geometry-snapshot", "frame": "revit_host_internal_feet",
        "scope": scope, "host_identity": ib.saved_document_identity(host),
        "link_identity": ib.saved_document_identity(linked), "link_instance_uid": str(link.UniqueId),
        "host": read_inventory(host, host_ids, DB.Transform.Identity, budget, clock),
        "link": read_inventory(linked, link_ids, link.GetTransform(), budget, clock),
    }
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > 2 * 1024 * 1024 or clock.ElapsedMilliseconds >= 10000:
        raise ReadError("Snapshot exceeded the query budget.")
    return {"status": "ok", "snapshot_json": encoded}


try:
    result = main()
except ReadError as error:
    result = {"status": "stopped", "message": str(error)}
except Exception:
    result = {"status": "stopped", "message": "Revit geometry or identity could not be read."}

# -*- coding: utf-8 -*-
"""Run the three Revit read scripts against small stand-ins (no Revit).

The document stand-ins have no transaction or write API, so a test fails
if a read script tries to change the model.
"""
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class Seq(list):
    @property
    def Count(self):
        return len(self)


class XYZ(object):
    BasisZ = None

    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class Line(object):
    def __init__(self, a, b):
        self.a, self.b = XYZ(*a), XYZ(*b)

    def Tessellate(self):
        return [self.a, self.b]


class Id(object):
    def __init__(self, value):
        self.Value = value


class Param(object):
    def __init__(self, value, storage="String", read_only=False, name=None):
        self.value, self.StorageType, self.IsReadOnly = value, storage, read_only
        self.Definition = NS(Name=name)

    def AsString(self):
        return self.value if self.StorageType == "String" else None

    def AsValueString(self):
        return str(self.value)

    def AsElementId(self):
        return Id(self.value)

    def AsInteger(self):
        return int(self.value)

    def AsDouble(self):
        return float(self.value)


class Room(object):
    def __init__(self, rid, loops, location=(5, 5, 0), area=100.0, params=None):
        self.Id, self.UniqueId, self.LevelId = Id(rid), "room-%d" % rid, Id(30)
        self.loops, self.Area, self.Perimeter = loops, area, 40.0
        self.Location = NS(Point=XYZ(*location)) if location else None
        self.params = params or {}

    def get_Parameter(self, bip):
        return self.params.get(bip)

    def LookupParameter(self, name):
        return self.params.get(name)

    def IsPointInRoom(self, point):
        return True

    def GetBoundarySegments(self, options):
        return Seq(Seq(NS(GetCurve=lambda c=c: c, ElementId=Id(70), LinkElementId=Id(-1)) for c in loop)
                   for loop in self.loops)

    def get_BoundingBox(self, view):
        return None


def square(x1, y1, x2, y2, z=0.0):
    pts = [(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)]
    return [Line(pts[i], pts[(i + 1) % 4]) for i in range(4)]


class Doc(object):
    IsFamilyDocument = False

    def __init__(self, elements):
        self.elements = elements

    def GetElement(self, element_id):
        value = element_id.Value if hasattr(element_id, "Value") else element_id
        return self.elements.get(value)


def base_db(collector):
    bip = NS(ROOM_NUMBER="number", ROOM_NAME="name", SYMBOL_NAME_PARAM="symbol_name",
             FLOOR_PARAM_IS_STRUCTURAL="structural", FLOOR_HEIGHTABOVELEVEL_PARAM="offset",
             FLOOR_ATTR_THICKNESS_PARAM="thickness", REF_TABLE_ELEM_NAME="key_name",
             ROOM_FINISH_FLOOR="floor_finish", ROOM_FINISH_BASE="base_finish",
             ROOM_FINISH_WALL="wall_finish", ROOM_FINISH_CEILING="ceiling_finish")
    return NS(
        Architecture=NS(Room=Room), BuiltInParameter=bip,
        BuiltInCategory=NS(OST_Rooms="rooms", OST_Floors="floors"),
        ElementId=lambda value: Id(value if isinstance(value, int) else -2000160),
        XYZ=XYZ, UV=lambda u, v: (u, v),
        SpatialElementBoundaryOptions=lambda: NS(),
        SpatialElementBoundaryLocation=NS(Finish="finish", Center="center"),
        StorageType=NS(String="String", ElementId="ElementId"), ViewSchedule="ViewSchedule",
        FilteredElementCollector=collector,
    )


@pytest.fixture
def run(monkeypatch):
    def execute(script, db, doc, inputs):
        monkeypatch.setitem(sys.modules, "pyrevit.api", NS(DB=db))
        monkeypatch.setitem(sys.modules, "System", NS(Int64=int))
        monkeypatch.setitem(sys.modules, "System.Collections.Generic", NS(List=ListFactory()))
        out = runpy.run_path(str(SCRIPTS / script), init_globals={"doc": doc, "inputs": inputs})
        result = out["result"]
        if "payload" in result:
            return json.loads(result["payload"])
        return result
    return execute


class ListFactory(object):
    def __getitem__(self, _):
        return DotNetList


class DotNetList(list):
    Add = list.append


class Collector(object):
    def __init__(self, items):
        self.items = items

    def __call__(self, doc, view_id=None):
        return self

    def OfCategory(self, _):
        return self

    def OfClass(self, _):
        return self

    def WhereElementIsNotElementType(self):
        return self

    def WherePasses(self, _):
        return self

    def __iter__(self):
        return iter(self.items)


def test_room_shapes_reads_loops_points_and_sources(run):
    room = Room(1, [square(0, 0, 10, 10), square(2, 2, 4, 4)],
                params={"number": Param("101"), "name": Param("Office")})
    doc = Doc({1: room, 30: NS(Name="Level 1"), 70: NS(Category=NS(Name="Walls"))})
    report = run("read_room_shapes.py", base_db(Collector([])), doc, {"room_ids": [1, 2]})
    assert report["kind"] == "room-shape-read"
    assert report["complete"] is True
    first, missing = report["rooms"]
    assert first["number"] == "101" and first["level_name"] == "Level 1"
    assert first["loops"][0] == [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert first["loop_sources"][1]["categories"] == ["Walls"]
    assert first["location"] == [5, 5, 0]
    assert missing["reason"] == "room_not_found"


def test_room_shapes_rejects_bad_inputs_and_family_documents(run):
    db = base_db(Collector([]))
    assert run("read_room_shapes.py", db, Doc({}), {})["error"] == "bad_inputs"
    assert run("read_room_shapes.py", db, Doc({}), {"room_ids": list(range(1, 502))})["error"] == "bad_inputs"
    family = Doc({})
    family.IsFamilyDocument = True
    assert run("read_room_shapes.py", db, family, {"room_ids": [1]})["error"] == "no_project_document"


def test_room_keys_reads_driven_parameters_and_usage(run):
    key_param = Param(50, storage="ElementId")
    finish = Param("FIN-1", read_only=True, name="Floor Finish")
    rooms = [Room(i, [], params={"number": Param(str(i)), "name": Param("R"), "Room Style": key_param,
                                 "floor_finish": finish}) for i in (1, 2, 3)]
    key = NS(get_Parameter=lambda bip: Param("SHARED") if bip == "key_name" else None,
             LookupParameter=lambda name: Param("FIN-1") if name == "Floor Finish" else None)
    schedule = NS(IsTemplate=False, Id=Id(900), Name="Room Style Key", KeyScheduleParameterName="Room Style",
                  Definition=NS(IsKeySchedule=True, CategoryId=Id(-2000160), GetFieldCount=lambda: 2,
                                GetField=lambda i: NS(GetName=lambda: ["Room Style", "Floor Finish"][i])))

    class KeyCollector(Collector):
        def __call__(self, doc, view_id=None):
            if view_id is not None:
                return Collector([key])
            return self

        def OfClass(self, _):
            return Collector([schedule])

    doc = Doc({1: rooms[0], 2: rooms[1], 50: key})
    report = run("read_room_keys.py", base_db(KeyCollector(rooms)), doc, {"room_ids": [1, 2]})
    assert report["key_schedules"][0]["fields"] == ["Floor Finish"]
    assert report["key_schedules"][0]["key_names"] == ["SHARED"]
    assert report["targets"][0]["keys"]["Room Style"] == {"key_id": 50, "key_name": "SHARED"}
    assert report["targets"][0]["values"]["Floor Finish"]["read_only"] is True
    assert report["key_usage"]["Room Style"]["50"]["count"] == 3
    assert report["key_rows"]["50"]["values"]["Floor Finish"] == "FIN-1"
    assert report["scan_complete"] is True


class Face(object):
    def __init__(self, z, area):
        self.FaceNormal, self.Area = XYZ(0, 0, z), area


class Solid(object):
    def __init__(self, volume, faces):
        self.Volume, self.Faces = volume, faces


class CurveLoop(list):
    Append = list.append

    def IsOpen(self):
        return False

    @staticmethod
    def CreateViaTransform(loop, transform):
        return loop


def test_floor_coverage_intersects_each_floor_with_the_room(run):
    room = Room(1, [square(0, 0, 10, 10)], params={"number": Param("101"), "name": Param("Office")})
    floor_solid = Solid(2.0, [Face(1, 100.0), Face(-1, 100.0)])

    class Floor(object):
        def __init__(self, fid, structural):
            self.Id, self.UniqueId, self.LevelId, self.GroupId = Id(fid), "f-%d" % fid, Id(30), Id(-1)
            self.Pinned = False
            self.params = {"structural": Param(1 if structural else 0), "offset": Param(0.0),
                           "thickness": Param(0.02)}

        def GetTypeId(self):
            return Id(11)

        def get_Parameter(self, bip):
            return self.params.get(bip)

        def get_Geometry(self, options):
            return [floor_solid]

        def get_BoundingBox(self, view):
            return NS(Max=XYZ(0, 0, 0), Min=XYZ(0, 0, -0.02))

    floors = [Floor(201, False), Floor(300, True)]
    calls = []

    def intersect(a, b, kind):
        calls.append(kind)
        return Solid(1.0, [Face(1, 40.0), Face(0, 5.0)])

    db = base_db(Collector(floors))
    db.Solid, db.PlanarFace, db.GeometryInstance = Solid, Face, type("GeometryInstance", (), {})
    db.Options = lambda: NS()
    db.ViewDetailLevel = NS(Fine="fine")
    db.CurveLoop = CurveLoop
    db.Transform = NS(CreateTranslation=lambda v: None)
    db.GeometryCreationUtilities = NS(CreateExtrusionGeometry=lambda loops, d, h: "prism")
    db.Outline = lambda a, b: (a, b)
    db.BoundingBoxIntersectsFilter = lambda outline: outline
    db.BooleanOperationsUtils = NS(ExecuteBooleanOperation=intersect)
    db.BooleanOperationsType = NS(Intersect="intersect")
    doc = Doc({1: room, 30: NS(Name="Level 1"), 11: NS(get_Parameter=lambda b: Param("Finish A"))})
    report = run("read_floor_room_coverage.py", db, doc, {"room_ids": [1], "floor_ids": [201, 300]})
    assert report["complete"] is True
    assert report["rooms"][0]["boundary_z_ft"] == 0.0
    assert [p["overlap_sf"] for p in report["pairs"]] == [40.0, 40.0]
    assert calls == ["intersect", "intersect"]
    slab = [f for f in report["floors"] if f["id"] == 300][0]
    assert slab["is_structural"] is True and slab["top_area_sf"] == 100.0
    assert report["floors"][0]["type_name"] == "Finish A"


def test_floor_coverage_limits_rooms(run):
    db = base_db(Collector([]))
    result = run("read_floor_room_coverage.py", db, Doc({}), {"room_ids": list(range(1, 22))})
    assert result["error"] == "bad_inputs"
    result = run("read_floor_room_coverage.py", db, Doc({}), {"room_ids": [1], "z_below_ft": 0})
    assert result["error"] == "bad_inputs"

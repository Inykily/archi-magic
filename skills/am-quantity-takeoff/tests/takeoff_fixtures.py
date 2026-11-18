"""A small synthetic Revit model for the scope query and the material quantity query."""
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace as NS

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]
SCOPE_SCRIPT = SKILL / "scripts" / "read_takeoff_scope.py"
MERGE_SCRIPT = SKILL / "scripts" / "merge_takeoff.py"
QUANTITY_SCRIPT = ROOT / "skills" / "am-material-audit" / "scripts" / "read_material_quantities.py"
CARBON_SCRIPT = ROOT / "skills" / "am-material-audit" / "scripts" / "carbon_report.py"

WALLS, FLOORS, ROOMS, TAGS, WALL_SWEEPS = -2000011, -2000032, -2000160, -2000220, -2000999
MODEL, ANNOTATION = "Model", "Annotation"


class ElementId:
    Value = None

    def __init__(self, value):
        self.Value = value


class Level:
    def __init__(self, value, name):
        self.Id = ElementId(value)
        self.Name = name


class Phase:
    def __init__(self, value, name="New Construction"):
        self.Id = ElementId(value)
        self.Name = name


class Status:
    New, Existing, Demolished, Temporary = "New", "Existing", "Demolished", "Temporary"


class Element:
    def __init__(self, value, category, level, materials, option=None, phase="New"):
        self.Id = ElementId(value)
        self.Category = category
        self.LevelId = ElementId(level)
        self.DesignOption = option
        self.phase = phase
        self.materials = materials

    def GetPhaseStatus(self, phase_id):
        return self.phase

    def GetMaterialIds(self, paint):
        return [] if paint else [ElementId(key) for key in sorted(self.materials)]

    def GetMaterialArea(self, material_id, paint):
        return 0.0 if paint else self.materials[material_id.Value][0]

    def GetMaterialVolume(self, material_id):
        return self.materials[material_id.Value][1]


def category(value, name, quantities=True, kind=MODEL, parent=None):
    return NS(Id=ElementId(value), Name=name, HasMaterialQuantities=quantities, CategoryType=kind, Parent=parent)


class Model:
    """Walls and floors on two levels, one floor without a level, one secondary design option."""

    def __init__(self):
        self.categories = {
            WALLS: category(WALLS, "Walls"), FLOORS: category(FLOORS, "Floors"),
            ROOMS: category(ROOMS, "Rooms", quantities=False),
            TAGS: category(TAGS, "Generic Annotations", kind=ANNOTATION),
        }
        self.categories[WALL_SWEEPS] = category(WALL_SWEEPS, "Sweeps", parent=self.categories[WALLS])
        primary, secondary = NS(IsPrimary=True), NS(IsPrimary=False)
        walls, floors = self.categories[WALLS], self.categories[FLOORS]
        self.items = {
            10: Level(10, "Level 1"), 20: Level(20, "Level 2"), 5: Phase(5),
            100: NS(Name="Material A"), 200: NS(Name="Material B"), 300: NS(Name="Material C"),
        }
        for element in (
            Element(101, walls, 10, {100: (10.0, 2.0)}),
            Element(102, walls, 10, {100: (10.0, 2.0), 200: (5.0, 0.5)}, phase="Demolished"),
            Element(103, walls, 20, {100: (20.0, 4.0)}),
            Element(104, walls, 10, {100: (99.0, 9.0)}, option=secondary),
            Element(105, walls, 20, {200: (4.0, 0.25)}, option=primary),
            Element(201, floors, 10, {300: (50.0, 10.0)}),
            Element(202, floors, -1, {300: (30.0, 6.0)}),
        ):
            self.items[element.Id.Value] = element
        self.path = "C:/Projects/Project A.rvt"

    def elements_of(self, category_id):
        return [item for item in self.items.values()
                if isinstance(item, Element) and item.Category.Id.Value == category_id]

    def document(self):
        model = self
        return NS(IsFamilyDocument=False, PathName=self.path,
                  ProjectInformation=NS(UniqueId="project-a-uid"),
                  Settings=NS(Categories=list(self.categories.values())), Phases=[self.items[5]],
                  GetElement=lambda element_id: model.items.get(element_id.Value))

    def db(self):
        model = self

        class Collector:
            def __init__(self, document):
                self.category_id = None

            def OfCategoryId(self, category_id):
                self.category_id = category_id.Value
                return self

            def WhereElementIsNotElementType(self):
                return iter(model.elements_of(self.category_id))

        names = {"OST_Walls": WALLS, "OST_Floors": FLOORS, "OST_Rooms": ROOMS, "OST_GenericAnnotation": TAGS}
        return NS(
            ElementId=ElementId, Level=Level, Phase=Phase, ElementOnPhaseStatus=Status,
            CategoryType=NS(Model=MODEL, Annotation=ANNOTATION),
            BuiltInCategory=NS(**names),
            Category=NS(GetCategory=lambda document, builtin: model.categories.get(builtin)),
            FilteredElementCollector=Collector,
            UnitUtils=NS(ConvertFromInternalUnits=lambda value, unit: value * unit),
            UnitTypeId=NS(SquareMeters=1.0, CubicMeters=1.0),
        )


def install(monkeypatch, model):
    db = model.db()
    monkeypatch.setitem(sys.modules, "pyrevit", NS(api=NS(DB=db)))
    monkeypatch.setitem(sys.modules, "pyrevit.api", NS(DB=db))
    monkeypatch.setitem(sys.modules, "System", NS(Int32=int, Int64=int))


def run_script(path, model, inputs):
    return runpy.run_path(str(path), init_globals={"doc": model.document(), "inputs": inputs})


def scope_result(monkeypatch, model, inputs):
    install(monkeypatch, model)
    return run_script(SCOPE_SCRIPT, model, inputs)["result"]


def quantity_result(monkeypatch, model, element_ids):
    install(monkeypatch, model)
    return run_script(QUANTITY_SCRIPT, model, {"element_ids": list(element_ids)})["result"]


def runtime(result, **overrides):
    """Wrap a script result like a saved run_query response."""
    record = {"status": "succeeded", "mode": "query", "run_id": "run-1", "exit_code": 0,
              "result_truncated": False,
              "changes": {"added_count": 0, "modified_count": 0, "deleted_count": 0},
              "result": result}
    record.update(overrides)
    return record


def save(path, record):
    path.write_text(json.dumps(record), encoding="utf-8")
    return path

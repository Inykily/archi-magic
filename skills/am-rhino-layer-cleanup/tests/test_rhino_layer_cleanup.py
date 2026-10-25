"""Offline tests for the layer cleanup scripts (no Rhino needed). Run: python -m unittest discover -s tests"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", "scripts", name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


plan = load("rhino_layer_plan")
apply_ = load("rhino_layer_apply")

LAYERS = [
    {"index": 0, "id": "g0", "path": "Default", "parent": None},
    {"index": 1, "id": "g1", "path": "Site", "parent": None},
    {"index": 2, "id": "g2", "path": "Site::Trees", "parent": 1},
    {"index": 3, "id": "g3", "path": "Site::Roads", "parent": 1},
    {"index": 4, "id": "g4", "path": "Old", "parent": None},
    {"index": 5, "id": "g5", "path": "Old::Sub", "parent": 4},
    {"index": 6, "id": "g6", "path": "Work", "parent": None},
]


class EmptyPlan(unittest.TestCase):
    def test_children_first_and_rules(self):
        # Objects on Site::Trees; current layer is Work.
        out = plan.empty_layer_plan(LAYERS, {2: 3}, current_index=6)
        self.assertEqual([x["path"] for x in out], ["Old::Sub", "Site::Roads", "Old"])

    def test_default_never_deleted(self):
        out = plan.empty_layer_plan(LAYERS, {}, current_index=6)
        self.assertNotIn("Default", [x["path"] for x in out])

    def test_parent_of_current_layer_kept(self):
        out = plan.empty_layer_plan(LAYERS, {}, current_index=5)
        paths = [x["path"] for x in out]
        self.assertNotIn("Old", paths)
        self.assertNotIn("Old::Sub", paths)

    def test_layer_with_objects_kept(self):
        out = plan.empty_layer_plan(LAYERS, {6: 1}, current_index=0)
        self.assertNotIn("Work", [x["path"] for x in out])


class Duplicates(unittest.TestCase):
    def test_case_space_underscore_dash(self):
        g = plan.duplicate_groups(["Walls", "walls", "Wall s", "Doors", "Site::Tree_Line", "Site::tree-line", "Site::Trees"])
        self.assertEqual(g, [["Site::Tree_Line", "Site::tree-line"], ["Wall s", "Walls", "walls"]])

    def test_same_name_different_parent_not_duplicate(self):
        self.assertEqual(plan.duplicate_groups(["A::Doors", "B::Doors"]), [])


class Apply(unittest.TestCase):
    def test_delete_order_deepest_first(self):
        items = [{"id": "a", "path": "Old"}, {"id": "b", "path": "Old::Sub::X"}, {"id": "c", "path": "Old::Sub"}]
        self.assertEqual([x["id"] for x in apply_.delete_order(items)], ["b", "c", "a"])

    def test_validate_nothing_to_do(self):
        self.assertTrue(apply_.validate_inputs({}))

    def test_validate_move_needs_target(self):
        self.assertIn("move_object_ids given without move_to_layer", apply_.validate_inputs({"move_object_ids": ["x"]}))

    def test_validate_ok(self):
        self.assertEqual(apply_.validate_inputs({"delete_layer_ids": ["g4"]}), [])

    def test_plan_feeds_apply(self):
        # The plan's empty_layers are already in apply's delete order.
        out = plan.empty_layer_plan(LAYERS, {2: 3}, current_index=6)
        self.assertEqual([x["path"] for x in apply_.delete_order(out)], [x["path"] for x in out])


if __name__ == "__main__":
    unittest.main()

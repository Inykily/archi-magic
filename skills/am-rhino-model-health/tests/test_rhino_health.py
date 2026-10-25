"""Offline tests for scripts/rhino_health.py (no Rhino needed). Run: python -m unittest discover -s tests"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rhino_health", os.path.join(HERE, "..", "scripts", "rhino_health.py"))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


class Tolerance(unittest.TestCase):
    def test_typical_mm_doc_is_fine(self):
        self.assertEqual(h.tolerance_findings("Millimeters", 0.01, 0.001), [])

    def test_rhino_default_mm_template_is_on_the_boundary_not_flagged(self):
        # 0.001 mm = 1e-6 m exactly: not finer than the limit.
        self.assertEqual(h.tolerance_findings("Millimeters", 0.001, 0.001), [])

    def test_coarse_feet_tolerance_flagged(self):
        f = h.tolerance_findings("Feet", 0.01, 0.3048)
        self.assertEqual([x["code"] for x in f], ["TOL_COARSE"])

    def test_too_fine_flagged(self):
        f = h.tolerance_findings("Meters", 1e-9, 1.0)
        self.assertEqual([x["code"] for x in f], ["TOL_FINE"])

    def test_zero_is_error(self):
        self.assertEqual(h.tolerance_findings("Meters", 0, 1.0)[0]["severity"], "error")


class Layers(unittest.TestCase):
    LAYERS = [
        {"index": 0, "path": "Default", "parent": None},
        {"index": 1, "path": "Site", "parent": None},
        {"index": 2, "path": "Site::Trees", "parent": 1},
        {"index": 3, "path": "Site::Roads", "parent": 1},
        {"index": 4, "path": "Old", "parent": None},
    ]

    def test_parent_with_used_child_is_not_empty(self):
        self.assertEqual(h.empty_layers(self.LAYERS, {2: 5}), ["Default", "Old", "Site::Roads"])

    def test_all_empty(self):
        self.assertEqual(h.empty_layers(self.LAYERS, {}), sorted(l["path"] for l in self.LAYERS))

    def test_subtree_counts(self):
        self.assertEqual(h.subtree_object_counts(self.LAYERS, {2: 2, 3: 1, 1: 1})[1], 4)


class Blocks(unittest.TestCase):
    DEFS = {0: {"name": "Chair", "nested": []}, 1: {"name": "Table set", "nested": [0]},
            2: {"name": "Old door", "nested": []}, 3: {"name": "Unused group", "nested": [2]}}

    def test_nested_use_counts_as_used(self):
        self.assertEqual(h.unused_block_names(self.DEFS, {1}), ["Old door", "Unused group"])

    def test_nothing_placed(self):
        self.assertEqual(h.unused_block_names(self.DEFS, set()), ["Chair", "Old door", "Table set", "Unused group"])

    def test_unknown_ref_ignored(self):
        self.assertEqual(h.unused_block_names(self.DEFS, {99, 3}), ["Chair", "Table set"])


class Misc(unittest.TestCase):
    def test_small_threshold(self):
        self.assertTrue(h.is_small(0.009, 0.001))
        self.assertFalse(h.is_small(0.01, 0.001))

    def test_rank_order_stable(self):
        f = [{"code": "a", "severity": "info"}, {"code": "b", "severity": "error"}, {"code": "c", "severity": "info"}, {"code": "d", "severity": "warn"}]
        self.assertEqual([x["code"] for x in h.rank(f)], ["b", "d", "a", "c"])

    def test_no_rhino_import_at_load(self):
        # Loading the module must not need Rhino: main() only runs inside Rhino.
        self.assertTrue(callable(h.main))


if __name__ == "__main__":
    unittest.main()

"""Offline tests for scripts/rhino_area_report.py (no Rhino needed). Run: python -m unittest discover -s tests"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rhino_area_report", os.path.join(HERE, "..", "scripts", "rhino_area_report.py"))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class Units(unittest.TestCase):
    def test_mm2_to_m2(self):
        self.assertAlmostEqual(a.to_m2(1_000_000, 0.001), 1.0)

    def test_ft2_to_m2(self):
        self.assertAlmostEqual(a.to_m2(1.0, 0.3048), 0.09290304)

    def test_m2_to_ft2(self):
        self.assertAlmostEqual(a.m2_to_ft2(1.0), 10.7639104167, places=8)

    def test_round_trip_feet(self):
        # 100 ft2 drawn in feet must report 100 ft2.
        self.assertAlmostEqual(a.m2_to_ft2(a.to_m2(100.0, 0.3048)), 100.0, places=6)


class LayerFilter(unittest.TestCase):
    def test_no_filter_selects_all(self):
        self.assertTrue(a.layer_selected("Any::Thing", []))

    def test_sublayer_selected(self):
        self.assertTrue(a.layer_selected("Plans::L1::Rooms", ["Plans::L1"]))

    def test_name_prefix_is_not_a_sublayer(self):
        self.assertFalse(a.layer_selected("Plans::L10", ["Plans::L1"]))


class Summary(unittest.TestCase):
    ITEMS = [
        {"layer": "Rooms", "group": "Office", "area": 20_000_000.0},
        {"layer": "Rooms", "group": "Office", "area": 10_000_000.0},
        {"layer": "Rooms", "group": "Lab", "area": 15_000_000.0},
        {"layer": "Core", "group": "", "area": 5_000_000.0},
    ]

    def test_groups_and_sorting(self):
        rows, _ = a.summarize(self.ITEMS, 0.001)
        self.assertEqual([(r["layer"], r["group"], r["count"]) for r in rows],
                         [("Core", "", 1), ("Rooms", "Lab", 1), ("Rooms", "Office", 2)])

    def test_values_in_m2(self):
        rows, totals = a.summarize(self.ITEMS, 0.001)
        self.assertEqual([r["area_m2"] for r in rows], [5.0, 15.0, 30.0])
        self.assertEqual(totals["area_m2"], 50.0)
        self.assertEqual(totals["count"], 4)

    def test_empty(self):
        rows, totals = a.summarize([], 1.0)
        self.assertEqual(rows, [])
        self.assertEqual(totals["area_m2"], 0)

    def test_csv_header_uses_unit_label(self):
        rows, _ = a.summarize(self.ITEMS[:1], 0.001)
        header, data = a.csv_table(rows, "mm")
        self.assertEqual(header[3], "area_mm2")
        self.assertEqual(data[0][:3], ["Rooms", "Office", 1])


if __name__ == "__main__":
    unittest.main()

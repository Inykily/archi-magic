# -*- coding: utf-8 -*-
"""Tests for rhino_option_export.py (issue #198)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import rhino_option_export as roe  # noqa: E402


def test_parent_aware_visibility_blocks_child_when_parent_is_off():
    layers = [
        {"id": "L1", "full_path": "Option A", "parent_id": None, "visible": False, "color": [0, 0, 0]},
        {"id": "L2", "full_path": "Option A::Massing", "parent_id": "L1", "visible": True, "color": [0, 0, 0]},
        {"id": "L3", "full_path": "Option B", "parent_id": None, "visible": True, "color": [120, 140, 160]},
        {"id": "L4", "full_path": "Option B::Massing", "parent_id": "L3", "visible": True, "color": [10, 10, 10]},
    ]
    vis = roe.effective_layer_visibility(layers)
    assert vis["L1"] is False
    # Child layer L2 has visible=True, but parent L1 is False -> effective is False
    assert vis["L2"] is False
    assert vis["L3"] is True
    assert vis["L4"] is True


def test_plan_option_export_crops_strays_remaps_black_and_warns_save_small():
    layers = [
        {"id": "L3", "full_path": "Option B", "parent_id": None, "visible": True, "color": [0, 0, 0]},
        {"id": "L4", "full_path": "Option B::Tower", "parent_id": "L3", "visible": True, "color": [5, 5, 5]},
    ]
    objects = [
        # Valid building object with render mesh
        {"id": "o1", "layer_id": "L4", "object_type": "brep", "has_render_mesh": True, "bbox": [[0, 0, 0], [80, 80, 120]]},
        # Stray copy parked far below grade (z = -500 ft)
        {"id": "o2", "layer_id": "L4", "object_type": "brep", "has_render_mesh": True, "bbox": [[0, 0, -520], [50, 50, -480]]},
        # Stray piece 2,500 ft away from site center
        {"id": "o3", "layer_id": "L4", "object_type": "mesh", "has_render_mesh": True, "bbox": [[2400, 0, 0], [2500, 50, 20]]},
        # Brep without render mesh (Save Small)
        {"id": "o4", "layer_id": "L4", "object_type": "brep", "has_render_mesh": False, "bbox": [[10, 10, 0], [40, 40, 60]]},
    ]

    plan = roe.plan_option_export(
        layers, objects, "Option B",
        re_root_name="OptB",
        z_min=-100.0,
        center_xy=(0.0, 0.0),
        max_radius=1500.0,
    )
    assert plan["export_root"] == "OptB"
    assert plan["remapped_black_layers"] == 2
    assert plan["layers"][1]["export_path"] == "OptB::Tower"
    assert plan["layers"][1]["color"] == [200, 200, 200]
    assert plan["dropped_below_z"] == 1
    assert plan["dropped_outside_radius"] == 1
    assert plan["exported_objects"] == 1
    assert plan["missing_render_mesh_count"] == 1
    assert any("Save Small" in w for w in plan["warnings"])


def test_read_3dm_sequential_retries_once_on_cloud_none():
    calls = []

    def fake_reader(path):
        calls.append(path)
        # First call for cloud_a.3dm returns None while downloading; second call succeeds
        if path == "cloud_a.3dm" and calls.count("cloud_a.3dm") == 1:
            return None
        return {"file": path}

    res = roe.read_3dm_sequential(["cloud_a.3dm", "cloud_b.3dm"], fake_reader)
    assert calls == ["cloud_a.3dm", "cloud_a.3dm", "cloud_b.3dm"]
    assert res[0]["loaded"] is True and res[0]["retried"] is True
    assert res[1]["loaded"] is True and res[1]["retried"] is False

# -*- coding: utf-8 -*-
"""Tests for recipe_library.py (issue #179: team recipe library and proven fast path).

Run:
    python -m pytest skills/am-safe-change/tests/test_recipe_library.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RECIPE_LIB_SCRIPT = os.path.join(HERE, "..", "scripts", "recipe_library.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import recipe_library as rl


def test_save_and_list_recipes(tmp_path):
    recipes_dir = str(tmp_path / "recipes")
    rec, fp = rl.save_recipe(
        recipes_dir=recipes_dir,
        name="Repath Textures",
        description="Fix broken material asset paths",
        script_code="print('repath')",
        tested_years=["2025", "2026"],
        author="alice",
        run_id="run-101",
    )

    assert os.path.exists(fp)
    assert rec["slug"] == "repath_textures"
    assert rec["runs_count"] == 1
    assert rec["proven"] is False  # Only 1 run, threshold is 3

    all_recipes = rl.list_recipes(recipes_dir)
    assert len(all_recipes) == 1
    assert all_recipes[0]["name"] == "Repath Textures"

    # Search keyword
    assert len(rl.list_recipes(recipes_dir, keyword="textures")) == 1
    assert len(rl.list_recipes(recipes_dir, keyword="sheets")) == 0


def test_earns_proven_after_three_clean_runs(tmp_path):
    recipes_dir = str(tmp_path / "recipes")
    rec, fp = rl.save_recipe(recipes_dir, "Renumber Sheets", "Safe sheet shift", "pass", run_id="run-1")
    assert rec["proven"] is False

    # Run 2: clean
    rec2 = rl.record_run(fp, run_id="run-2", dryrun_matched_preview=True)
    assert rec2["consecutive_clean_runs"] == 2
    assert rec2["proven"] is False

    # Run 3: clean -> earns PROVEN
    rec3 = rl.record_run(fp, run_id="run-3", dryrun_matched_preview=True)
    assert rec3["consecutive_clean_runs"] == 3
    assert rec3["proven"] is True


def test_stale_guard_failure_stops_fast_path():
    proven_recipe = {
        "name": "Proven Task",
        "proven": True,
        "proven_threshold": 3,
    }

    # Clean stale guard: hashes match
    ok, msg = rl.evaluate_fast_path(proven_recipe, baseline_hash="abc", current_hash="abc")
    assert ok is True
    assert "Fast path approved" in msg

    # Broken stale guard: hashes differ
    ok_stale, msg_stale = rl.evaluate_fast_path(proven_recipe, baseline_hash="abc", current_hash="xyz")
    assert ok_stale is False
    assert "Model changed since the preview" in msg_stale


def test_regression_drops_proven_status(tmp_path):
    recipes_dir = str(tmp_path / "recipes")
    rec, fp = rl.save_recipe(recipes_dir, "Tested Task", "desc", "pass", run_id="run-1")
    rl.record_run(fp, "run-2", dryrun_matched_preview=True)
    rec3 = rl.record_run(fp, "run-3", dryrun_matched_preview=True)
    assert rec3["proven"] is True

    # Run 4: dry-run did not match preview -> drops back to normal mode
    rec4 = rl.record_run(fp, "run-4", dryrun_matched_preview=False)
    assert rec4["proven"] is False
    assert rec4["consecutive_clean_runs"] == 0


def test_cli_execution(tmp_path):
    recipes_dir = str(tmp_path / "recipes")
    proc = subprocess.run([
        sys.executable, RECIPE_LIB_SCRIPT, "save",
        "--name", "Fast Shift",
        "--desc", "Quick sheet renumber",
        "--run-id", "run-55",
        "--dir", recipes_dir,
    ], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "Saved recipe 'Fast Shift'" in proc.stdout

    proc_list = subprocess.run([
        sys.executable, RECIPE_LIB_SCRIPT, "list",
        "--dir", recipes_dir,
    ], capture_output=True, text=True)
    assert proc_list.returncode == 0
    assert "Fast Shift" in proc_list.stdout

# -*- coding: utf-8 -*-
"""Tests for mcp_guards.py (issue #195)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import mcp_guards as mg  # noqa: E402


def test_capture_view_rejects_view_id_alias():
    res = mg.validate_capture_view({"view_id": 12345})
    assert res["ok"] is False
    assert "unknown argument 'view_id'; use 'view'" in res["error"]


def test_capture_view_detects_mismatched_active_view():
    res = mg.validate_capture_view(
        {"view": "Area Schedule Drafting"},
        result={"view_name": "Level 1 - Gross Building", "view_id": 999, "mode": "export"},
    )
    assert res["ok"] is False
    assert "does not match requested view" in res["error"]
    assert "MISMATCH" in res["line"]


def test_capture_view_accepts_matching_view_and_formats_line():
    res = mg.validate_capture_view(
        {"view": "Drafting View 1"},
        result={"view_name": "Drafting View 1", "view_id": 450},
    )
    assert res["ok"] is True
    assert res["line"] == "Captured view: Drafting View 1 (requested: Drafting View 1)"


def test_reconcile_post_sync_elements_detects_renumbered_ids_not_deleted():
    committed = [
        {"id": 5001, "guid": "11111111-2222-3333-4444-555555555555", "name": "SharedParamA"},
        {"id": 5002, "unique_id": "uid-abc-2", "name": "BindingB"},
        {"id": 5003, "stable_key": "Level 2:10.0,25.0", "name": "Area 201"},
    ]
    current = [
        {"id": 6101, "guid": "11111111-2222-3333-4444-555555555555", "name": "SharedParamA"},
        {"id": 6102, "unique_id": "uid-abc-2", "name": "BindingB"},
        {"id": 6103, "stable_key": "Level 2:10.0,25.0", "name": "Area 201"},
    ]
    out = mg.reconcile_post_sync_elements(committed, current)
    assert out["status"] == "ids_renumbered_at_sync"
    assert out["missing"] == []
    assert len(out["id_changed"]) == 3
    assert "ids changed" in out["message"] or "id(s) changed" in out["message"]
    assert "Sync with Central" in out["message"]


def test_reconcile_post_sync_elements_reports_truly_missing():
    committed = [{"id": 5001, "unique_id": "uid-gone"}]
    current = [{"id": 6101, "unique_id": "uid-other"}]
    out = mg.reconcile_post_sync_elements(committed, current)
    assert out["status"] == "missing_elements"
    assert out["missing"] == [5001]
    assert "no longer exist" in out["message"]

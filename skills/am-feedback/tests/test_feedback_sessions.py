# -*- coding: utf-8 -*-
"""Tests for feedback_sessions.py (issue #201)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import feedback_sessions as fs  # noqa: E402


def test_archived_sessions_included_by_default_and_wrong_brief_id_resolved_by_title():
    sessions = [
        {"id": "s1", "title": "Coordinator", "archived": False, "last_activity": "2026-11-06T21:00:00Z"},
        {"id": "s2", "title": "Area Restore Child", "archived": True, "last_activity": "2026-11-06T18:30:00Z"},
        {"id": "s3", "title": "Rhino Viewer Child", "archived": True, "last_activity": "2026-11-06T19:15:00Z"},
        {"id": "s4", "title": "Old Session", "archived": True, "last_activity": "2026-11-01T10:00:00Z"},
    ]
    brief_refs = [{"id": "wrong-id-999", "title": "Area Restore Child"}]

    res = fs.select_sessions_for_date(sessions, "2026-11-06", brief_refs=brief_refs)
    selected_ids = [s["id"] for s in res["selected"]]
    assert selected_ids == ["s1", "s2", "s3"]
    assert res["selected"][1]["matched_by"] == "title"
    assert res["selected"][1]["resolved_from_brief_id"] == "wrong-id-999"
    assert len(res["skipped"]) == 1 and res["skipped"][0]["id"] == "s4"

    header = fs.format_sessions_read_header(res["selected"], res["skipped"])
    assert "Sessions read: Coordinator (active, 2026-11-06); Area Restore Child (archived, 2026-11-06)" in header
    assert "Sessions skipped: Old Session (last active on 2026-11-01, not 2026-11-06)." in header


def test_slice_events_for_date_pages_back_from_end_and_stops_at_earlier_day():
    # Simulate a 2,000+ message session where 2,000 events are from earlier days and 3 are from today
    old_events = [{"id": i, "created_at": "2026-11-04T12:00:00Z", "text": "old"} for i in range(2000)]
    today_events = [
        {"id": 2001, "created_at": "2026-11-06T09:00:00Z", "text": "today 1"},
        {"id": 2002, "created_at": "2026-11-06T10:00:00Z", "text": "today 2"},
        {"id": 2003, "created_at": "2026-11-06T11:00:00Z", "text": "today 3"},
    ]
    all_events = old_events + today_events

    sliced = fs.slice_events_for_date(all_events, "2026-11-06")
    assert sliced["events_read_count"] == 3
    assert sliced["stopped_at_earlier_day"] is True
    # Only scanned the 3 today events + 1 earlier-day boundary event = 4 events!
    assert sliced["events_scanned_from_end"] == 4
    assert [e["id"] for e in sliced["events"]] == [2001, 2002, 2003]


def test_filter_already_posted_today_deduplicates_same_day_feedback():
    candidates = [
        {"title": "capture_view ignores view_id", "signature": "unknown argument view_id"},
        {"title": "New area scheme dependent bug", "signature": "AreaScheme.GetDependentElements"},
    ]
    posted_today = [
        {"title": "capture_view ignores view_id", "signature": "unknown argument view_id"},
    ]
    res = fs.filter_already_posted_today(candidates, posted_today)
    assert len(res["novel"]) == 1
    assert res["novel"][0]["title"] == "New area scheme dependent bug"
    assert len(res["already_posted_today"]) == 1

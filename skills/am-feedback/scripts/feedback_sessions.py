# -*- coding: utf-8 -*-
"""Multi-session discovery, date slicing, and 'Sessions read' formatting for am-feedback (issue #201).

When the user asks for feedback on more than the current session (for example
"all sessions today"), am-feedback:
1. Includes archived sessions by default (include_archived=True) and resolves
   wrong brief session IDs by matching session titles and activity dates.
2. Reads only the events of the asked date by paging backward from the newest
   event and stopping at the first event of an earlier day.
3. Starts every draft with a "Sessions read" summary line (title, archived or
   active, date range read) and lists skipped sessions with their reasons.
4. Filters out points already posted that day in issues or comments by other
   feedback sessions.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from typing import Any, Dict, List, Optional


def _date_prefix(ts: Optional[str]) -> str:
    if not ts:
        return ""
    return str(ts).strip()[:10]


def select_sessions_for_date(
    sessions: List[Dict[str, Any]],
    target_date: str,
    include_archived: bool = True,
    brief_refs: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Select sessions active on target_date (archived included by default).

    Also resolves brief_refs ([{"id": ..., "title": ...}]) by title when an ID
    in a hand-off brief is wrong.
    """
    tdate = _date_prefix(target_date)
    by_id = {str(s.get("id") or ""): s for s in (sessions or []) if s.get("id")}
    by_title = {str(s.get("title") or "").strip().lower(): s for s in (sessions or []) if s.get("title")}

    resolved_ids = set()
    id_remaps = {}
    for ref in brief_refs or []:
        rid = str(ref.get("id") or "")
        rtitle = str(ref.get("title") or "").strip().lower()
        if rid and rid in by_id:
            resolved_ids.add(rid)
        elif rtitle and rtitle in by_title:
            actual = by_title[rtitle]
            aid = str(actual.get("id") or "")
            resolved_ids.add(aid)
            if rid:
                id_remaps[aid] = rid

    selected: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for s in sessions or []:
        sid = str(s.get("id") or "")
        title = str(s.get("title") or sid or "untitled")
        archived = bool(s.get("archived", False))
        last_date = _date_prefix(s.get("last_activity") or s.get("updated_at") or s.get("date"))

        if archived and not include_archived:
            skipped.append({"id": sid, "title": title, "archived": archived, "reason": "archived excluded"})
            continue

        if tdate and last_date and last_date != tdate and sid not in resolved_ids:
            skipped.append({
                "id": sid,
                "title": title,
                "archived": archived,
                "reason": f"last active on {last_date}, not {tdate}",
            })
            continue

        entry = {
            "id": sid,
            "title": title,
            "archived": archived,
            "date_read": tdate or last_date or "unknown",
        }
        if sid in id_remaps:
            entry["resolved_from_brief_id"] = id_remaps[sid]
            entry["matched_by"] = "title"
        selected.append(entry)

    return {"selected": selected, "skipped": skipped}


def slice_events_for_date(events: List[Dict[str, Any]], target_date: str) -> Dict[str, Any]:
    """Page backward from newest event and stop at the first event of an earlier day."""
    tdate = _date_prefix(target_date)
    kept_reversed: List[Dict[str, Any]] = []
    stopped_early = False
    events_scanned = 0

    for ev in reversed(events or []):
        events_scanned += 1
        ev_date = _date_prefix(ev.get("created_at") or ev.get("timestamp") or ev.get("date"))
        if not ev_date:
            kept_reversed.append(ev)
            continue
        if ev_date == tdate:
            kept_reversed.append(ev)
        elif ev_date < tdate:
            stopped_early = True
            break

    kept = list(reversed(kept_reversed))
    return {
        "target_date": tdate,
        "total_events_in_session": len(events or []),
        "events_scanned_from_end": events_scanned,
        "events_read_count": len(kept),
        "stopped_at_earlier_day": stopped_early,
        "events": kept,
    }


def format_sessions_read_header(selected: List[Dict[str, Any]], skipped: Optional[List[Dict[str, Any]]] = None) -> str:
    """Format the 'Sessions read' and 'Sessions skipped' lines for the start of a feedback draft."""
    if not selected:
        read_line = "Sessions read: none."
    else:
        parts = []
        for s in selected:
            state = "archived" if s.get("archived") else "active"
            dr = s.get("date_read") or s.get("date_range") or "full"
            parts.append(f"{s.get('title')} ({state}, {dr})")
        read_line = "Sessions read: " + "; ".join(parts) + "."

    if not skipped:
        return read_line

    skip_parts = [f"{s.get('title')} ({s.get('reason')})" for s in skipped]
    skip_line = "Sessions skipped: " + "; ".join(skip_parts) + "."
    return read_line + "\n" + skip_line


def filter_already_posted_today(
    candidates: List[Dict[str, Any]],
    posted_today: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Filter out candidate themes already posted in today's issues or comments."""
    seen_sigs = set()
    seen_titles = set()
    for p in posted_today or []:
        sig = str(p.get("signature") or "").strip().lower()
        title = str(p.get("title") or "").strip().lower()
        if sig:
            seen_sigs.add(sig)
        if title:
            seen_titles.add(title)

    novel = []
    duplicates = []
    for c in candidates or []:
        csig = str(c.get("signature") or "").strip().lower()
        ctitle = str(c.get("title") or "").strip().lower()
        if (csig and csig in seen_sigs) or (ctitle and ctitle in seen_titles):
            duplicates.append(c)
        else:
            novel.append(c)
    return {"novel": novel, "already_posted_today": duplicates}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Filter and format multi-session feedback reads.")
    ap.add_argument("input", help="Path to sessions JSON")
    ap.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    ap.add_argument("--exclude-archived", action="store_true", help="Exclude archived sessions")
    args = ap.parse_args(argv)

    with io.open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    sessions = data if isinstance(data, list) else data.get("sessions", [])
    res = select_sessions_for_date(
        sessions,
        target_date=args.date,
        include_archived=not args.exclude_archived,
        brief_refs=data.get("brief_refs") if isinstance(data, dict) else None,
    )
    print(format_sessions_read_header(res["selected"], res["skipped"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

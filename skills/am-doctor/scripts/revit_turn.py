# -*- coding: utf-8 -*-
"""Revit turn-holder lock and stale-message check (issue #200).

When several agent sessions share one Revit instance, relayed chat messages
("you have the Revit turn", "Revit is free") can arrive out of order or become
stale. A session that pauses waiting for the user can also hold the turn while
Revit is idle.

This tool manages a small holder file at:
    %LOCALAPPDATA%\\archi-magic\\state\\revit-turn.json

Commands:
    python revit_turn.py status [--file <path>] [--message-time <epoch_or_iso>]
    python revit_turn.py claim --session <name> --task "<text>" [--pid <pid>] [--force] [--file <path>]
    python revit_turn.py release --session <name> [--force] [--file <path>]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
import os
import sys
import time
from typing import Any, Dict, Optional


def default_holder_path(revit_pid: Optional[int] = None) -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "archi-magic", "state")
    name = f"revit-turn-{revit_pid}.json" if revit_pid else "revit-turn.json"
    return os.path.join(folder, name)


def _parse_time(val: Optional[str]) -> Optional[float]:
    if val is None or str(val).strip() == "":
        return None
    s = str(val).strip()
    try:
        return float(s)
    except ValueError:
        pass
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def read_holder(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    target = path or default_holder_path()
    if not os.path.isfile(target):
        return None
    try:
        with io.open(target, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def get_turn_status(path: Optional[str] = None, message_time: Optional[str] = None) -> Dict[str, Any]:
    """Return current Revit turn holder and check whether a relayed message is stale."""
    target = path or default_holder_path()
    holder = read_holder(target)
    msg_epoch = _parse_time(message_time)

    if holder is None:
        mtime = os.path.getmtime(target) if os.path.exists(target) else None
        stale = bool(msg_epoch is not None and mtime is not None and msg_epoch < mtime)
        return {
            "held": False,
            "session": None,
            "task": None,
            "since": None,
            "since_epoch": None,
            "stale_message": stale,
            "line": "Revit turn is free (no holder file). Call get_context to confirm.",
        }

    since_epoch = float(holder.get("claimed_epoch") or 0.0)
    stale = bool(msg_epoch is not None and since_epoch > 0 and msg_epoch < since_epoch)
    session = str(holder.get("session") or "unknown")
    task = str(holder.get("task") or "unspecified task")
    since = str(holder.get("claimed_at") or "")
    line = f"Revit is held by session '{session}' since {since} (task: {task})."
    if stale:
        line += " Ignore the older turn message (older than holder file)."

    return {
        "held": True,
        "session": session,
        "task": task,
        "revit_pid": holder.get("revit_pid"),
        "since": since,
        "since_epoch": since_epoch,
        "stale_message": stale,
        "line": line,
    }


def claim_turn(
    session: str,
    task: str,
    path: Optional[str] = None,
    revit_pid: Optional[int] = None,
    force: bool = False,
    now_epoch: Optional[float] = None,
) -> Dict[str, Any]:
    """Claim the Revit turn for a session."""
    target = path or default_holder_path(revit_pid)
    existing = read_holder(target)
    if existing and existing.get("session") != session and not force:
        return {
            "ok": False,
            "held_by": existing.get("session"),
            "since": existing.get("claimed_at"),
            "task": existing.get("task"),
            "line": (
                f"Cannot claim turn: held by '{existing.get('session')}' "
                f"since {existing.get('claimed_at')} ({existing.get('task')})."
            ),
        }

    ts = float(now_epoch if now_epoch is not None else time.time())
    iso = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parent = os.path.dirname(os.path.abspath(target))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    payload = {
        "session": str(session),
        "task": str(task),
        "revit_pid": revit_pid,
        "claimed_at": iso,
        "claimed_epoch": ts,
    }
    with io.open(target, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, indent=2))

    return {
        "ok": True,
        "session": str(session),
        "task": str(task),
        "since": iso,
        "since_epoch": ts,
        "line": f"Turn claimed by '{session}' at {iso} ({task}).",
    }


def release_turn(
    session: str,
    path: Optional[str] = None,
    revit_pid: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Release the Revit turn when finished or when waiting for user input."""
    target = path or default_holder_path(revit_pid)
    existing = read_holder(target)
    if existing is None:
        return {"ok": True, "released": False, "line": "Turn is already free."}

    holder_session = str(existing.get("session") or "")
    if holder_session != str(session) and not force:
        return {
            "ok": False,
            "released": False,
            "held_by": holder_session,
            "line": f"Cannot release turn: currently held by '{holder_session}', not '{session}'.",
        }

    if os.path.exists(target):
        os.remove(target)
    return {
        "ok": True,
        "released": True,
        "line": f"Turn released by '{session}'.",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Manage the local Revit turn-holder file.")
    sub = ap.add_subparsers(dest="cmd")

    st = sub.add_parser("status")
    st.add_argument("--file", help="Custom holder file path")
    st.add_argument("--pid", type=int, help="Revit process ID")
    st.add_argument("--message-time", help="Timestamp (epoch or ISO-8601) of a relayed turn message")

    cl = sub.add_parser("claim")
    cl.add_argument("--session", required=True, help="Session name or ID")
    cl.add_argument("--task", required=True, help="Short task description")
    cl.add_argument("--pid", type=int, help="Revit process ID")
    cl.add_argument("--force", action="store_true", help="Override an existing holder")
    cl.add_argument("--file", help="Custom holder file path")

    rl = sub.add_parser("release")
    rl.add_argument("--session", required=True, help="Session name or ID")
    rl.add_argument("--pid", type=int, help="Revit process ID")
    rl.add_argument("--force", action="store_true", help="Release even if held by another session")
    rl.add_argument("--file", help="Custom holder file path")

    args = ap.parse_args(argv)
    path = getattr(args, "file", None) or (default_holder_path(getattr(args, "pid", None)) if getattr(args, "pid", None) else None)

    if args.cmd == "status":
        res = get_turn_status(path=path, message_time=args.message_time)
        print(res["line"])
        return 0
    if args.cmd == "claim":
        res = claim_turn(args.session, args.task, path=path, revit_pid=args.pid, force=args.force)
        print(res["line"])
        return 0 if res["ok"] else 1
    if args.cmd == "release":
        res = release_turn(args.session, path=path, revit_pid=args.pid, force=args.force)
        print(res["line"])
        return 0 if res["ok"] else 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

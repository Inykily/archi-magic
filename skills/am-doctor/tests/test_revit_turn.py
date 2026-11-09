# -*- coding: utf-8 -*-
"""Tests for revit_turn.py (issue #200)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import revit_turn as rt  # noqa: E402


def test_claim_status_and_release_turn(tmp_path):
    holder_file = str(tmp_path / "revit-turn.json")

    # Initially free
    st0 = rt.get_turn_status(path=holder_file)
    assert st0["held"] is False

    # Session A claims turn
    c1 = rt.claim_turn("session-a", "parameter migration", path=holder_file, now_epoch=1700000100.0)
    assert c1["ok"] is True

    # Session B can see who holds Revit and since when without asking coordinator
    st1 = rt.get_turn_status(path=holder_file)
    assert st1["held"] is True
    assert st1["session"] == "session-a"
    assert st1["task"] == "parameter migration"
    assert "session-a" in st1["line"]

    # Session B cannot overwrite without force
    c2 = rt.claim_turn("session-b", "sheet renumber", path=holder_file)
    assert c2["ok"] is False
    assert c2["held_by"] == "session-a"

    # Session A releases when waiting on user
    rel = rt.release_turn("session-a", path=holder_file)
    assert rel["ok"] is True and rel["released"] is True

    # Session B can now claim
    c3 = rt.claim_turn("session-b", "sheet renumber", path=holder_file, now_epoch=1700000200.0)
    assert c3["ok"] is True


def test_stale_relayed_message_older_than_holder_file_is_flagged(tmp_path):
    holder_file = str(tmp_path / "revit-turn.json")
    rt.claim_turn("session-b", "verify discard", path=holder_file, now_epoch=1700000500.0)

    # Message sent at epoch 1700000300 (before session-b claimed at 1700000500)
    st_old = rt.get_turn_status(path=holder_file, message_time="1700000300")
    assert st_old["stale_message"] is True
    assert "Ignore the older turn message" in st_old["line"]

    # Newer message sent at epoch 1700000600
    st_new = rt.get_turn_status(path=holder_file, message_time="1700000600")
    assert st_new["stale_message"] is False

# -*- coding: utf-8 -*-
"""Tests for time_log.py (issue #184: local time-saved log and ROI calculator).

Run:
    python -m pytest skills/am-doctor/tests/test_time_log.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TIME_LOG_SCRIPT = os.path.join(HERE, "..", "scripts", "time_log.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import time_log as tl


def test_estimate_minutes_defaults():
    assert tl.estimate_minutes("am-safe-change", 5) == 30
    assert tl.estimate_minutes("am-param-qa", 0) == 45
    assert tl.estimate_minutes("am-area-report", 8) == 60
    assert tl.estimate_minutes("unknown-skill", 2) == 20
    # Scaled elements: 50 elements -> base 30 + (50 - 10) / 20 = 30 + 2 = 32
    assert tl.estimate_minutes("am-safe-change", 50) == 32


def test_ten_logged_runs_match_monthly_sum(tmp_path):
    log_file = str(tmp_path / "time-saved.jsonl")

    # Log 10 runs across 2 skills in November 2026
    expected_minutes = 0
    expected_elements = 0
    for i in range(10):
        skill = "am-safe-change" if i % 2 == 0 else "am-param-qa"
        elems = 10 + i * 2
        rec = tl.append_log(
            log_path=log_file,
            date_str="2026-11-%02d" % (i + 1),
            skill=skill,
            element_count=elems,
            model_name="sample.rvt",
        )
        expected_minutes += rec["estimated_minutes"]
        expected_elements += elems

    records = tl.read_logs(log_file)
    assert len(records) == 10

    months = tl.monthly_summary(records)
    assert len(months) == 1
    nov = months[0]
    assert nov["month"] == "2026-11"
    assert nov["total_runs"] == 10
    assert nov["total_elements"] == expected_elements
    assert nov["total_minutes"] == expected_minutes
    assert nov["total_hours"] == round(expected_minutes / 60.0, 1)
    assert len(nov["by_skill"]) == 2
    assert nov["by_skill"]["am-safe-change"]["runs"] == 5
    assert nov["by_skill"]["am-param-qa"]["runs"] == 5


def test_roi_calculation(tmp_path):
    log_file = str(tmp_path / "time-saved.jsonl")
    tl.append_log(log_file, "2026-10-15", "am-safe-change", 20, estimated_minutes=60)
    tl.append_log(log_file, "2026-11-01", "am-param-qa", 30, estimated_minutes=120)

    records = tl.read_logs(log_file)
    roi = tl.calculate_roi(records, hourly_rate=150.0)

    assert roi["total_runs"] == 2
    assert roi["total_hours_saved"] == 3.0  # (60 + 120) / 60
    assert roi["total_cost_saved"] == 450.0  # 3.0 * 150.0
    assert "Estimates based on standard manual task minutes" in roi["assumptions"]


def test_what_if_roi():
    res = tl.what_if("am-param-qa", monthly_frequency=4, hourly_rate=100.0, custom_minutes=60)
    assert res["monthly_frequency"] == 4
    assert res["monthly_hours_saved"] == 4.0
    assert res["annual_hours_saved"] == 48.0
    assert res["monthly_cost_saved"] == 400.0
    assert res["annual_cost_saved"] == 4800.0


def test_cli_end_to_end(tmp_path):
    log_file = str(tmp_path / "time.jsonl")

    # 1. Log a task
    proc = subprocess.run([
        sys.executable, TIME_LOG_SCRIPT, "log",
        "--skill", "am-material-audit",
        "--elements", "25",
        "--minutes", "45",
        "--log", log_file,
    ], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "Logged: am-material-audit (45 mins)" in proc.stdout

    # 2. Report JSON
    proc = subprocess.run([
        sys.executable, TIME_LOG_SCRIPT, "report",
        "--log", log_file,
        "--json",
    ], capture_output=True, text=True)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert len(data) == 1
    assert data[0]["total_runs"] == 1
    assert data[0]["total_minutes"] == 45

    # 3. ROI JSON
    proc = subprocess.run([
        sys.executable, TIME_LOG_SCRIPT, "roi",
        "--rate", "100",
        "--log", log_file,
        "--json",
    ], capture_output=True, text=True)
    assert proc.returncode == 0
    roi = json.loads(proc.stdout)
    assert roi["total_cost_saved"] == 75.0  # 45/60 * 100 = 0.75 * 100 = 75.0

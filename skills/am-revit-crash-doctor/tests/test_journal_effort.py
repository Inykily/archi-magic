import json
import os
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "journal_effort.py"


def marker(time, day="01"):
    return f"'E {day}-Nov-2026 {time}.000; 0:<\n"


def model(path):
    return f"' 0:< [ISL] On open, Adler Checksum: TEST [{path}]\n"


def command(identifier):
    return f'Jrn.Command "Ribbon", "Synthetic command , ID_{identifier}"\n'


def journal(path, contents, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding=encoding)


def report(root, *options):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--from", "2026-11-01",
         "--to", "2026-11-02", *options],
        capture_output=True, text=True, check=False,
    )
    return result.returncode, json.loads(result.stdout)


def test_event_dates_clipping_and_distinct_models(tmp_path):
    prefix = marker("23:59:48", "31").replace("31-Nov", "31-Oct")
    before_midnight = marker("23:59:58", "31").replace("31-Nov", "31-Oct")
    for year, directory, encoding in ((2025, "alpha", "utf-16"), (2026, "beta", "utf-8-sig")):
        path = tmp_path / f"Autodesk Revit {year}" / "Journals" / "journal.0001.txt"
        journal(path, prefix + model(f"C:\\private\\{directory}\\shared.rvt") + before_midnight
                + command("WALL_CREATE") + marker("00:00:03"), encoding)
        os.utime(path, (0, 0))

    code, data = report(tmp_path)
    assert code == 0
    assert data["coverage"] == {"read": 2}
    assert data["activity_windows"] == [
        {"model": "model-1", "command_family": "wall", "estimated_ms": 3000},
        {"model": "model-2", "command_family": "wall", "estimated_ms": 3000},
    ]
    assert "private" not in json.dumps(data)
    assert "shared.rvt" not in json.dumps(data)


def test_multimodel_conflict_and_long_gap_stay_unassigned(tmp_path):
    journal(tmp_path / "journal.0002.txt",
            marker("12:00:00") + model(r"C:\first.rvt") + marker("12:00:01")
            + command("WALL_CREATE") + marker("12:00:05")
            + model(r"C:\second.rvt") + marker("12:00:06")
            + command("WALL_CREATE") + command("WALL_DELETE") + marker("12:00:09")
            + command("WALL_CREATE") + marker("12:02:00"))
    code, data = report(tmp_path)
    assert code == 0
    assert data["activity_windows"] == [
        {"model": None, "command_family": "wall", "estimated_ms": 4000},
    ]
    assert data["unassigned_ms"] == {"ambiguous_or_no_command": 5000, "long_gap": 111000}


def test_reports_partial_unreadable_undated_and_outside_range(tmp_path):
    journal(tmp_path / "journal.0001.txt", marker("12:00:00") + "unfinished line")
    (tmp_path / "journal.0002.txt").write_bytes(b"\xff\xff\xff")
    journal(tmp_path / "journal.0003.txt", command("WALL_CREATE"))
    journal(tmp_path / "journal.0004.txt", marker("12:00:00", "02"))
    code, data = report(tmp_path)
    assert code == 2
    assert data["status"] == "incomplete"
    assert data["coverage"] == {"partial": 1, "unreadable": 1, "undated": 1, "outside_range": 1}
    assert data["activity_windows"] == []

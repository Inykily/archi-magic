"""Tests for scripts/slow_check.py (issue #287). Synthetic snapshots only: no real PC data."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import slow_check  # noqa: E402

SCRIPT = SCRIPTS / "slow_check.py"


def proc(pid, ppid, name, created, cpu=0.0, mem=10.0, path=None):
    return {"pid": pid, "ppid": ppid, "name": name, "path": path or ("C:\\Apps\\" + name),
            "cmd": "", "created": created, "cpu_s": cpu, "mem_mb": mem}


def snapshot():
    return {
        "now": "2026-11-20T15:00:00.0000000-05:00",
        "since": "2026-11-20T00:00:00.0000000-05:00",
        "boot": "2026-11-10T08:00:00.0000000-05:00",
        "total_mem_mb": 32768, "free_mem_mb": 2048, "logical_cpus": 8,
        "processes": [
            proc(0, 0, "System Idle Process", None, cpu=99999),
            proc(4, 0, "System", "2026-11-10T08:00:00", cpu=50),
            proc(700, 4, "services.exe", "2026-11-10T08:00:05"),
            proc(900, 700, "svchost.exe", "2026-11-10T08:00:10"),
            proc(1000, 888, "explorer.exe", "2026-11-20T08:00:00", cpu=20),
            proc(2000, 1000, "Revit.exe", "2026-11-20T09:00:00", cpu=900, mem=6000),
            proc(2100, 2000, "RenderHost.exe", "2026-11-20T09:00:20", cpu=286, mem=400),
            proc(2110, 2100, "RenderWorker.exe", "2026-11-20T09:01:00", cpu=50, mem=100),
            proc(3000, 1000, "Launcher.exe", "2026-11-20T08:00:30", cpu=30, mem=50),
            proc(3001, 3000, "Launcher.exe", "2026-11-20T08:00:31", cpu=30, mem=50),
            proc(3002, 3000, "Launcher.exe", "2026-11-20T08:00:32", cpu=30, mem=50),
            proc(4000, 700, "VendorUpdate.exe", "2026-11-10T08:01:00", cpu=120, mem=80),
            proc(5000, 900, "Nightly.exe", "2026-11-20T03:00:00", cpu=200, mem=60),
            proc(6000, 1000, "Viewer.exe", "2026-11-20T10:00:00", cpu=100, mem=900),
            # Parent number 7777 now belongs to a process that started later: PID reuse.
            proc(7777, 1000, "Late.exe", "2026-11-20T14:00:00", cpu=1, mem=5),
            proc(8000, 7777, "Orphan.exe", "2026-11-20T11:00:00", cpu=150, mem=70),
            proc(9000, 700, "MsMpEng.exe", "2026-11-10T08:00:20", cpu=5000, mem=500),
        ],
        "run": [
            {"where": "HKCU", "name": "LauncherAuto", "cmd": '"C:\\Apps\\Launcher.exe" --silent'},
            {"where": "HKCU", "name": "Other", "cmd": "C:\\Apps\\NotRunning.exe"},
        ],
        "services": [
            {"name": "VendorUpd", "display": "Vendor Update Service", "start": "Auto", "state": "Running",
             "pid": 4000, "cmd": "C:\\Apps\\VendorUpdate.exe"},
            {"name": "Schedule", "display": "Task Scheduler", "start": "Auto", "state": "Running",
             "pid": 900, "cmd": "C:\\Windows\\system32\\svchost.exe -k netsvcs"},
            {"name": "WinDefend", "display": "Defender", "start": "Auto", "state": "Running",
             "pid": 9000, "cmd": "MsMpEng.exe"},
        ],
        "tasks": [{"name": "Nightly job", "cmd": "C:\\Apps\\Nightly.exe", "triggers": ["Daily"]}],
        "events": [
            {"kind": "live_kernel", "time": "2026-11-20T10:00:00", "code": "141", "app": ""},
            {"kind": "live_kernel", "time": "2026-11-20T10:05:00", "code": "193", "app": ""},
            {"kind": "display_reset", "time": "2026-11-20T10:06:00", "code": "", "app": ""},
            {"kind": "hang", "time": "2026-11-20T11:00:00", "code": "", "app": "Revit.exe"},
            {"kind": "low_memory", "time": "2026-11-20T12:00:00", "code": "", "app": "Revit.exe, Viewer.exe"},
        ],
    }


def groups_by_name(result):
    return {g["name"]: g for g in result["top"]}


def test_origin_of_each_heavy_process():
    res = slow_check.analyze(snapshot())
    g = groups_by_name(res)
    assert g["RenderHost.exe"]["origin"] == "revit"
    assert g["RenderWorker.exe"]["origin"] == "revit"
    assert g["RenderWorker.exe"]["via"] == ["RenderHost.exe"]
    assert g["Launcher.exe"]["origin"] == "sign_in"
    assert g["Launcher.exe"]["count"] == 3
    assert "LauncherAuto" in g["Launcher.exe"]["detail"] and "starts hidden" in g["Launcher.exe"]["detail"]
    assert g["VendorUpdate.exe"]["origin"] == "service"
    assert "Auto" in g["VendorUpdate.exe"]["detail"]
    assert g["Nightly.exe"]["origin"] == "task"
    assert g["Viewer.exe"]["origin"] == "user"
    assert g["Revit.exe"]["origin"] == "user"
    assert g["MsMpEng.exe"]["origin"] == "security"


def test_pid_reuse_is_not_taken_as_parent():
    res = slow_check.analyze(snapshot())
    assert groups_by_name(res)["Orphan.exe"]["origin"] == "unknown"


def test_idle_is_left_out():
    res = slow_check.analyze(snapshot())
    assert "System Idle Process" not in groups_by_name(res)


def test_events_summary():
    ev = slow_check.summarize_events(snapshot()["events"])
    assert ev["gpu_resets"] == 2  # 141 and display 4101; 193 is not a GPU code
    assert ev["hangs"] == {"Revit.exe": 1}
    assert ev["low_memory"] == 1 and set(ev["low_memory_apps"]) == {"Revit.exe", "Viewer.exe"}


def test_actions_are_user_steps_only():
    res = slow_check.analyze(snapshot())
    text = "\n".join(res["actions"])
    assert "Restart the computer" in text          # 10 days uptime
    assert "Task Manager > Startup apps" in text and "LauncherAuto" in text
    assert "Revit starts RenderHost.exe" in text
    assert "Ask IT before you change a service" in text
    assert "scheduled task" in text
    assert "graphics driver" in text
    assert "Memory is low" in text                 # 6 % free and a low-memory event
    assert "MsMpEng" not in text                   # never suggest stopping security software


def test_report_never_says_the_user_runs_a_background_app():
    out = slow_check.render(slow_check.analyze(snapshot()), user="")
    assert "Nothing was ended, changed, deleted or uploaded." in out
    assert not re.search(r"\byou (run|use|opened)\b", out, re.IGNORECASE)
    line = [l for l in out.splitlines() if l.startswith("- RenderWorker.exe")][0]
    assert "started by Revit" in line and "RenderHost.exe > RenderWorker.exe" in line


def test_redaction_of_user_and_sid():
    s = "task 'Update-S-1-5-21-111-222-333-1001' for C:\\Users\\jdoe-test\\x"
    out = slow_check.redact(s, user="jdoe-test")
    assert "S-1-5-21" not in out and "jdoe-test" not in out and "<user>" in out


def test_exe_names_from_commands():
    assert slow_check.exe_names('"C:\\A B\\Tool.EXE" --x') == {"tool.exe"}
    assert slow_check.exe_names("rundll32.exe C:\\x\\y.dll") == {"rundll32.exe"}
    assert slow_check.exe_names("") == set()


def test_files_onedrive_cache_temp_and_journal(tmp_path):
    od = tmp_path / "OneDrive"
    (od / "Proj").mkdir(parents=True)
    big = od / "Proj" / "model.rvt"
    with open(big, "wb") as f:
        f.seek(2 * 1024 * 1024 - 1)
        f.write(b"\0")
    old = od / "Proj" / "old.rvt"
    old.write_bytes(b"\0" * 2048)
    os.utime(old, (time.time() - 5 * 86400, time.time() - 5 * 86400))
    local = tmp_path / "Local"
    jdir = local / "Autodesk" / "Revit" / "Autodesk Revit 2026" / "Journals"
    jdir.mkdir(parents=True)
    (jdir / "journal.0001.txt").write_text("x\n' DXGI_ERROR_DEVICE_REMOVED\nDXGI_ERROR_DEVICE_REMOVED y\n")
    cc = local / "Autodesk" / "Revit" / "Autodesk Revit 2026" / "CollaborationCache"
    cc.mkdir()
    (cc / "a.rvt").write_bytes(b"\0" * 1000)
    temp = tmp_path / "Temp"
    temp.mkdir()
    (temp / "t.tmp").write_bytes(b"\0" * 10)
    since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    env = {"OneDrive": str(od), "LOCALAPPDATA": str(local), "TEMP": str(temp)}
    rows, ok = slow_check.big_revit_files(str(od), since, time.time() + 10, min_mb=1)
    assert ok and [r["file"] for r in rows] == ["model.rvt"]
    files = slow_check.collect_files(since, env=env, budget=10)
    assert files["onedrive_folders"] == 1 and files["onedrive"] == []   # 2 MB is under the 100 MB limit
    assert files["journal_gpu_lines"] == 2 and files["journals_read"] == 1
    assert files["cache_gb"] == 0.0 and files["temp_gb"] == 0.0


def test_folder_walk_stops_at_the_deadline(tmp_path):
    (tmp_path / "a").mkdir()
    total, complete = slow_check.folder_size(str(tmp_path), time.time() - 1)
    assert complete is False


def test_cli_with_snapshot(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(snapshot()), encoding="utf-8")
    out_json = tmp_path / "out.json"
    r = subprocess.run([sys.executable, str(SCRIPT), "--snapshot", str(snap), "--no-files", "--json", str(out_json)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "Heavy processes" in r.stdout and "Safe next steps" in r.stdout
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["events"]["gpu_resets"] == 2


def test_cli_empty_snapshot_is_exit_2(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"processes": []}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--snapshot", str(snap), "--no-files"],
                       capture_output=True, text=True)
    assert r.returncode == 2


def test_script_is_read_only():
    """The check must never end a process, change a setting or delete a file."""
    src = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        r"Stop-Process", r"taskkill", r"\bkill\b", r"os\.kill", r"Set-ItemProperty", r"New-ItemProperty",
        r"Remove-Item", r"Set-Service", r"Stop-Service", r"Disable-ScheduledTask", r"Unregister-ScheduledTask",
        r"\breg\s+(add|delete)", r"sc\.exe", r"os\.remove", r"os\.unlink", r"shutil\.rmtree", r"rmdir",
        r"Invoke-WebRequest", r"Invoke-RestMethod", r"urllib", r"requests",
    ]
    for pat in forbidden:
        assert not re.search(pat, src, re.IGNORECASE), pat

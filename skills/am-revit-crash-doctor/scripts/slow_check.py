"""Read-only check for "Revit or the PC is slow" (issue #287).

It names the heavy processes and, for each one, what started it: Revit (an
add-in), Windows sign-in (a Run entry or a Startup folder shortcut), a Windows
service, a scheduled task, or the user (Windows Explorer). It also reads GPU
driver resets, application hangs, low-memory events, large Revit files saved
into OneDrive today, and the size of the Revit cloud cache and %TEMP%.

The check only reads. It never ends a process, never changes a setting, never
deletes a file, and never uploads anything.

    python slow_check.py                 # collect on this PC and print the report
    python slow_check.py --json out.json # also write the analysis as JSON
    python slow_check.py --snapshot s.json --no-files   # analyze a saved snapshot

Exit codes: 0 report done, 1 script error, 2 the process list could not be read.
"""

import argparse
import base64
from datetime import datetime, timedelta
import json
import ntpath
import os
import re
import subprocess
import sys
import time

TOP_N = 8
UPTIME_WARN_DAYS = 7
FREE_MEM_WARN_PCT = 10
ONEDRIVE_BIG_MB = 100
CACHE_WARN_GB = 20
TEMP_WARN_GB = 5
WALK_SECONDS = 25

REVIT = {"revit.exe"}
EXPLORER = {"explorer.exe"}
TASK_HOSTS = {"svchost.exe", "taskhostw.exe", "taskeng.exe"}
WINDOWS_CORE = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "memory compression", "fontdrvhost.exe",
    "dwm.exe", "sihost.exe", "taskhostw.exe", "userinit.exe", "runtimebroker.exe",
}
IDLE = {"system idle process", "idle"}
SECURITY = {
    "msmpeng.exe", "mssense.exe", "nissrv.exe", "sysmon.exe", "sysmon64.exe", "securityhealthservice.exe",
    "sgrmbroker.exe", "mpdefendercoreservice.exe",
}
EXE = re.compile(r"([^\\/\"'\s]+\.exe)\b", re.IGNORECASE)
SID = re.compile(r"S-1-5-21(-\d+)+", re.IGNORECASE)

ORIGIN_TEXT = {
    "revit": "started by Revit (most likely an add-in that starts with Revit)",
    "sign_in": "started by Windows at sign-in",
    "service": "a Windows service",
    "task": "started by a scheduled task",
    "user": "opened from Windows Explorer (Start menu, taskbar, desktop or a file)",
    "windows": "part of Windows",
    "security": "security software (keep it running)",
    "unknown": "start not known",
}


# --- collection (Windows only) ------------------------------------------------

COLLECTOR = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false
$since = (Get-Date).Date.AddDays(-__DAYSBACK__)
$o = [ordered]@{}
$os = Get-CimInstance Win32_OperatingSystem
$o.now = (Get-Date).ToString('o')
$o.since = $since.ToString('o')
if ($os) {
  $o.boot = $os.LastBootUpTime.ToString('o')
  $o.total_mem_mb = [math]::Round([double]$os.TotalVisibleMemorySize / 1024)
  $o.free_mem_mb = [math]::Round([double]$os.FreePhysicalMemory / 1024)
}
$o.logical_cpus = [Environment]::ProcessorCount
$o.processes = @(Get-CimInstance Win32_Process | ForEach-Object {
  [ordered]@{ pid = [int]$_.ProcessId; ppid = [int]$_.ParentProcessId; name = "$($_.Name)"
    path = "$($_.ExecutablePath)"; cmd = "$($_.CommandLine)"
    created = $(if ($_.CreationDate) { $_.CreationDate.ToString('o') } else { $null })
    cpu_s = [math]::Round(([double]$_.KernelModeTime + [double]$_.UserModeTime) / 1e7, 1)
    mem_mb = [math]::Round([double]$_.WorkingSetSize / 1MB, 1) } })
$run = New-Object System.Collections.ArrayList
$keys = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'
foreach ($k in $keys) {
  $item = Get-ItemProperty -LiteralPath $k
  if ($item) { foreach ($p in $item.PSObject.Properties) { if ($p.Name -notlike 'PS*') {
    [void]$run.Add([ordered]@{ where = $k.Substring(0, 4); name = $p.Name; cmd = "$($p.Value)" }) } } }
}
$sh = New-Object -ComObject WScript.Shell
foreach ($f in @([Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('CommonStartup'))) {
  if ($f -and (Test-Path -LiteralPath $f)) { foreach ($l in Get-ChildItem -LiteralPath $f -File) {
    $t = "$($l.FullName)"; if ($l.Extension -eq '.lnk' -and $sh) { $t = "$($sh.CreateShortcut($l.FullName).TargetPath)" }
    [void]$run.Add([ordered]@{ where = 'Startup folder'; name = $l.BaseName; cmd = $t }) } }
}
$o.run = @($run)
$o.services = @(Get-CimInstance Win32_Service | ForEach-Object {
  [ordered]@{ name = "$($_.Name)"; display = "$($_.DisplayName)"; start = "$($_.StartMode)"; state = "$($_.State)"
    pid = [int]$_.ProcessId; cmd = "$($_.PathName)" } })
$o.tasks = @(Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' } | ForEach-Object {
  $t = $_; foreach ($a in @($t.Actions)) { if ($a.Execute) {
    [ordered]@{ name = "$($t.TaskName)"; cmd = "$($a.Execute)"
      triggers = @($t.Triggers | ForEach-Object { "$($_.CimClass.CimClassName)" -replace '^MSFT_Task', '' -replace 'Trigger$', '' }) } } } })
$ev = New-Object System.Collections.ArrayList
foreach ($e in @(Get-WinEvent -FilterHashtable @{ LogName = 'Application'; StartTime = $since; Id = 1001, 1002 })) {
  $m = "$($e.Message)"
  if ($e.Id -eq 1001 -and $m -match 'LiveKernelEvent') {
    $code = ''; if ($m -match 'P1:\s*(\w+)') { $code = $Matches[1] }
    [void]$ev.Add([ordered]@{ kind = 'live_kernel'; time = $e.TimeCreated.ToString('o'); code = $code; app = '' })
  } elseif ($e.Id -eq 1002) {
    $app = ''; if ($e.Properties.Count -gt 0) { $app = "$($e.Properties[0].Value)" }
    [void]$ev.Add([ordered]@{ kind = 'hang'; time = $e.TimeCreated.ToString('o'); code = ''; app = $app })
  }
}
foreach ($e in @(Get-WinEvent -FilterHashtable @{ LogName = 'System'; StartTime = $since; Id = 2004, 4101 })) {
  if ($e.Id -eq 2004 -and $e.ProviderName -like '*Resource-Exhaustion*') {
    $apps = @([regex]::Matches("$($e.Message)", '([^\s\\]+\.exe) \(\d+\)') | ForEach-Object { $_.Groups[1].Value } | Select-Object -First 3) -join ', '
    [void]$ev.Add([ordered]@{ kind = 'low_memory'; time = $e.TimeCreated.ToString('o'); code = ''; app = $apps })
  } elseif ($e.Id -eq 4101) {
    [void]$ev.Add([ordered]@{ kind = 'display_reset'; time = $e.TimeCreated.ToString('o'); code = ''; app = '' })
  }
}
$o.events = @($ev)
$o | ConvertTo-Json -Depth 6 -Compress
"""


def collect_snapshot(days_back=0, timeout=90):
    """Run the read-only PowerShell collector and return its JSON as a dict."""
    script = COLLECTOR.replace("__DAYSBACK__", str(int(days_back)))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", encoded],
        capture_output=True, timeout=timeout,
    )
    text = proc.stdout.decode("utf-8", "replace").strip()
    start = text.find("{")
    if start < 0:
        raise RuntimeError("the process list could not be read (PowerShell exit %s)" % proc.returncode)
    return json.loads(text[start:])


# --- pure helpers -------------------------------------------------------------

def parse_time(value):
    """ISO time from PowerShell ('o' format) -> naive local datetime, or None."""
    if not value:
        return None
    text = str(value)
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?", text)
    if not m:
        return None
    base = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
    if m.group(2):
        base += timedelta(microseconds=int((m.group(2)[1:] + "000000")[:6]))
    return base


def exe_names(command):
    """Lower-case exe file names named in a command line or a path."""
    return {ntpath.basename(x).lower() for x in EXE.findall(command or "")}


def redact(text, user=None):
    text = SID.sub("<sid>", text or "")
    user = user if user is not None else os.environ.get("USERNAME", "")
    if user and len(user) > 2:
        text = re.sub(re.escape(user), "<user>", text, flags=re.IGNORECASE)
    return text


def proc_exe(proc):
    path = proc.get("path") or ""
    return (ntpath.basename(path) or proc.get("name") or "").lower()


class Tree(object):
    """Process tree with parent checks against PID reuse."""

    def __init__(self, processes):
        self.by_pid = {}
        for p in processes:
            if (p.get("name") or "").lower() in IDLE or p.get("pid") in (None, 0):
                continue
            p = dict(p)
            p["_created"] = parse_time(p.get("created"))
            self.by_pid[p["pid"]] = p

    def parent(self, proc):
        par = self.by_pid.get(proc.get("ppid"))
        if par is None or par is proc or par["pid"] == proc["pid"]:
            return None
        child_t, par_t = proc.get("_created"), par.get("_created")
        if child_t and par_t and par_t > child_t:
            return None  # the real parent closed and Windows reused its number
        return par

    def explorer_start(self):
        times = [p["_created"] for p in self.by_pid.values()
                 if (p.get("name") or "").lower() in EXPLORER and p.get("_created")]
        return min(times) if times else None


def origin_of(proc, tree, snap, depth=0):
    """Return a dict: kind (see ORIGIN_TEXT), detail, via (parent chain), action."""
    name = (proc.get("name") or "").lower()
    exe = proc_exe(proc)
    if exe in SECURITY or name in SECURITY:
        return _o("security", "Windows or IT security service", "")
    if name in EXPLORER:
        return _o("windows", "the Windows desktop (explorer.exe)", "")
    services = [s for s in snap.get("services") or [] if s.get("pid") and s.get("pid") == proc.get("pid")]
    if services:
        s = services[0]
        names = ", ".join(sorted({x.get("display") or x.get("name") for x in services}))
        if name == "svchost.exe":
            return _o("windows", "Windows service host: " + names, "")
        return _o("service", "service '%s' (start: %s)" % (names, s.get("start") or "?"),
                  "service:%s:%s" % (names, s.get("start") or ""))
    if name in REVIT:
        par = tree.parent(proc)
        return _o("user", "Revit itself, opened by %s" % ((par or {}).get("name") or "the user"), "")
    par = tree.parent(proc)
    par_name = ((par or {}).get("name") or "").lower()

    if par is None or par_name in EXPLORER:
        for entry in snap.get("run") or []:
            if exe and exe in exe_names(entry.get("cmd")):
                hidden = " (starts hidden)" if re.search(r"(^|\s)(--?|/)(silent|background|hidden|minimized|tray)\b",
                                                         entry.get("cmd") or "", re.IGNORECASE) else ""
                where = entry.get("where") or ""
                label = "Startup folder shortcut" if where == "Startup folder" else "Run entry in %s" % where
                note = ""
                start, exp = proc.get("_created"), tree.explorer_start()
                if start and exp and start - exp > timedelta(minutes=10):
                    note = "; it started later than sign-in, so it may also have been opened again"
                return _o("sign_in", "%s '%s'%s%s" % (label, entry.get("name"), hidden, note),
                          "startup:%s" % entry.get("name"))
    if par is None or par_name in TASK_HOSTS:
        for task in snap.get("tasks") or []:
            if exe and exe in exe_names(task.get("cmd")):
                trig = ", ".join(task.get("triggers") or []) or "no trigger listed"
                return _o("task", "scheduled task '%s' (trigger: %s)" % (task.get("name"), trig),
                          "task:%s" % task.get("name"))
    if par is None:
        if name in WINDOWS_CORE:
            return _o("windows", "Windows process", "")
        return _o("unknown", "the process that started it has closed", "")
    if par_name in REVIT:
        return _o("revit", "child of Revit.exe", "revit")
    if par_name in EXPLORER:
        return _o("user", "child of explorer.exe", "user")
    if name in WINDOWS_CORE or par_name in ("services.exe", "wininit.exe", "smss.exe", "winlogon.exe") \
            or (par_name in WINDOWS_CORE and par_name != "svchost.exe"):
        return _o("windows", "child of %s" % par.get("name"), "")
    if depth >= 12:
        return _o("unknown", "parent chain too long", "")
    up = origin_of(par, tree, snap, depth + 1)
    via = [par.get("name")] + up["via"]
    return dict(up, via=via)


def _o(kind, detail, action):
    return {"kind": kind, "detail": detail, "via": [], "action": action}


def group_processes(snap):
    """Group processes by exe name and origin. Return a list of dicts."""
    tree = Tree(snap.get("processes") or [])
    now = parse_time(snap.get("now")) or datetime.now()
    groups = {}
    for proc in tree.by_pid.values():
        org = origin_of(proc, tree, snap)
        key = ((proc.get("name") or "?").lower(), org["kind"], org["detail"])
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"name": proc.get("name") or "?", "count": 0, "cpu_s": 0.0, "mem_mb": 0.0,
                               "first_start": None, "origin": org["kind"], "detail": redact(org["detail"]),
                               "via": org["via"], "action": org["action"]}
        g["count"] += 1
        g["cpu_s"] += float(proc.get("cpu_s") or 0)
        g["mem_mb"] += float(proc.get("mem_mb") or 0)
        t = proc.get("_created")
        if t and (g["first_start"] is None or t < g["first_start"]):
            g["first_start"] = t
    out = []
    for g in groups.values():
        g["cpu_s"] = round(g["cpu_s"], 1)
        g["mem_mb"] = round(g["mem_mb"], 1)
        start = g.pop("first_start")
        g["started"] = start.strftime("%Y-%m-%d %H:%M") if start else ""
        g["age_h"] = round((now - start).total_seconds() / 3600.0, 1) if start else None
        out.append(g)
    return out


def top_groups(groups, n=TOP_N):
    by_cpu = sorted(groups, key=lambda g: -g["cpu_s"])[:n]
    by_mem = sorted(groups, key=lambda g: -g["mem_mb"])[:n]
    seen, out = set(), []
    for g in by_cpu + by_mem:
        k = id(g)
        if k not in seen:
            seen.add(k)
            out.append(g)
    return sorted(out, key=lambda g: (-g["cpu_s"], -g["mem_mb"]))


def summarize_events(events):
    out = {"gpu_resets": 0, "gpu_codes": {}, "hangs": {}, "low_memory": 0, "low_memory_apps": {}}
    for e in events or []:
        kind = e.get("kind")
        if kind == "live_kernel" and str(e.get("code")) in ("141", "117", "1a8"):
            out["gpu_resets"] += 1
            out["gpu_codes"][str(e.get("code"))] = out["gpu_codes"].get(str(e.get("code")), 0) + 1
        elif kind == "display_reset":
            out["gpu_resets"] += 1
            out["gpu_codes"]["display 4101"] = out["gpu_codes"].get("display 4101", 0) + 1
        elif kind == "hang":
            app = e.get("app") or "?"
            out["hangs"][app] = out["hangs"].get(app, 0) + 1
        elif kind == "low_memory":
            out["low_memory"] += 1
            for app in (e.get("app") or "").split(", "):
                if app:
                    out["low_memory_apps"][app] = out["low_memory_apps"].get(app, 0) + 1
    return out


# --- files (bounded walks) ------------------------------------------------------

def folder_size(root, deadline):
    """Total bytes under root. Returns (bytes, complete)."""
    total, stack = 0, [root]
    while stack:
        if time.time() > deadline:
            return total, False
        top = stack.pop()
        try:
            with os.scandir(top) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total, True


def big_revit_files(root, since, deadline, min_mb=ONEDRIVE_BIG_MB):
    """Large .rvt / .rws files written since `since` under root. Returns (rows, complete)."""
    rows, stack = [], [root]
    since_ts = time.mktime(since.timetuple())
    while stack:
        if time.time() > deadline:
            return rows, False
        top = stack.pop()
        try:
            with os.scandir(top) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.name.lower().endswith((".rvt", ".rws")):
                            st = e.stat(follow_symlinks=False)
                            if st.st_mtime >= since_ts and st.st_size >= min_mb * 1024 * 1024:
                                rows.append({"file": e.name, "mb": round(st.st_size / 1048576.0),
                                             "saved": datetime.fromtimestamp(st.st_mtime).strftime("%H:%M")})
                    except OSError:
                        pass
        except OSError:
            pass
    return sorted(rows, key=lambda r: -r["mb"]), True


def journal_gpu_lines(local_appdata, since, deadline):
    """Count DXGI_ERROR_DEVICE_REMOVED lines in Revit journals written since `since`."""
    count, files = 0, 0
    base = os.path.join(local_appdata, "Autodesk", "Revit")
    since_ts = time.mktime(since.timetuple())
    try:
        years = [d for d in os.listdir(base) if d.lower().startswith("autodesk revit 20")]
    except OSError:
        return 0, 0
    for y in years:
        jdir = os.path.join(base, y, "Journals")
        try:
            names = os.listdir(jdir)
        except OSError:
            continue
        for n in names:
            if time.time() > deadline:
                return count, files
            p = os.path.join(jdir, n)
            if not re.match(r"journal\.\d+\.txt$", n, re.IGNORECASE):
                continue
            try:
                if os.path.getmtime(p) < since_ts:
                    continue
                files += 1
                with open(p, "rb") as f:
                    for line in f:
                        if b"DXGI_ERROR_DEVICE_REMOVED" in line:
                            count += 1
            except OSError:
                pass
    return count, files


def collect_files(since, env=None, budget=WALK_SECONDS):
    env = env if env is not None else os.environ
    deadline = time.time() + budget
    out = {"onedrive": [], "onedrive_complete": True, "cache_gb": None, "cache_complete": True,
           "temp_gb": None, "temp_complete": True, "journal_gpu_lines": 0, "journals_read": 0}
    roots = []
    for k in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        v = env.get(k)
        if v and os.path.isdir(v) and v not in roots:
            roots.append(v)
    for r in roots:
        rows, ok = big_revit_files(r, since, deadline)
        out["onedrive"].extend(rows)
        out["onedrive_complete"] = out["onedrive_complete"] and ok
    out["onedrive_folders"] = len(roots)
    local = env.get("LOCALAPPDATA") or ""
    if local:
        c, n = journal_gpu_lines(local, since, deadline)
        out["journal_gpu_lines"], out["journals_read"] = c, n
        total, ok = 0, True
        base = os.path.join(local, "Autodesk", "Revit")
        try:
            years = [d for d in os.listdir(base) if d.lower().startswith("autodesk revit 20")]
        except OSError:
            years = []
        found = False
        for y in years:
            cc = os.path.join(base, y, "CollaborationCache")
            if os.path.isdir(cc):
                found = True
                b, done = folder_size(cc, deadline)
                total += b
                ok = ok and done
        if found:
            out["cache_gb"], out["cache_complete"] = round(total / 1073741824.0, 1), ok
    tmp = env.get("TEMP")
    if tmp and os.path.isdir(tmp):
        b, done = folder_size(tmp, deadline)
        out["temp_gb"], out["temp_complete"] = round(b / 1073741824.0, 1), done
    return out


# --- analysis and report --------------------------------------------------------

def analyze(snap, files=None):
    groups = group_processes(snap)
    top = top_groups(groups)
    events = summarize_events(snap.get("events"))
    now = parse_time(snap.get("now")) or datetime.now()
    boot = parse_time(snap.get("boot"))
    uptime_days = round((now - boot).total_seconds() / 86400.0, 1) if boot else None
    total, free = snap.get("total_mem_mb"), snap.get("free_mem_mb")
    free_pct = round(100.0 * free / total) if total and free is not None else None
    files = files or {}
    actions = []

    def add(text):
        if text not in actions:
            actions.append(text)

    if uptime_days is not None and uptime_days >= UPTIME_WARN_DAYS:
        add("Restart the computer. It has run %s days without a restart." % uptime_days)
    for g in top:
        a = g.get("action") or ""
        if g["origin"] == "revit":
            add("Revit starts %s each time it opens, even if you do not use it. To stop this, turn off the "
                "add-in that owns it (in the add-in's own settings), or ask IT to remove the add-in. "
                "Do not end the process while Revit is open." % g["name"])
        elif a.startswith("startup:"):
            add("To stop %s at sign-in: open Task Manager > Startup apps, select its entry (startup name '%s'; "
                "Task Manager can show the app name instead), and click Disable. "
                "It takes effect at the next sign-in." % (g["name"], a.split(":", 1)[1]))
        elif a.startswith("service:") and a.endswith(":Auto"):
            add("%s is a Windows service that starts with Windows (Automatic). Ask IT before you change a service."
                % g["name"])
        elif a.startswith("task:"):
            add("A scheduled task starts %s. Ask IT before you turn off a scheduled task." % g["name"])
    if events["gpu_resets"] or files.get("journal_gpu_lines"):
        add("The graphics driver reset. Ask IT to update the graphics driver. "
            "Run am-revit-crash-doctor for the Revit side.")
    if events["low_memory"] or (free_pct is not None and free_pct < FREE_MEM_WARN_PCT):
        add("Memory is low. Close programs that you do not use, and keep one Revit model open at a time.")
    if files.get("onedrive"):
        add("Large Revit files were saved into OneDrive today. OneDrive uploads each save and uses CPU. "
            "Ask your BIM lead where Revit local files belong, or pause OneDrive while you work.")
    if (files.get("cache_gb") or 0) >= CACHE_WARN_GB:
        add("The Revit cloud cache is large. Do not delete it while Revit is open. "
            "Ask your BIM lead before you clean it.")
    if (files.get("temp_gb") or 0) >= TEMP_WARN_GB:
        add("%TEMP% is large. Clean it with Windows Settings > System > Storage > Temporary files.")
    return {
        "uptime_days": uptime_days,
        "free_mem_pct": free_pct,
        "total_mem_mb": total,
        "logical_cpus": snap.get("logical_cpus"),
        "since": snap.get("since"),
        "events": events,
        "top": top,
        "files": files,
        "actions": actions,
    }


def render(result, user=None):
    L = []
    L.append("Revit or PC is slow: read-only check")
    L.append("Nothing was ended, changed, deleted or uploaded.")
    L.append("")
    up = result["uptime_days"]
    L.append("Uptime: %s days since the last restart." % (up if up is not None else "not known"))
    if result["free_mem_pct"] is not None:
        L.append("Free memory now: %s%% of %s GB." % (result["free_mem_pct"],
                                                     round((result["total_mem_mb"] or 0) / 1024.0)))
    ev = result["events"]
    since = (result.get("since") or "")[:10]
    L.append("Since %s: graphics driver resets %d%s, application hangs %d, low-memory events %d." % (
        since or "today", ev["gpu_resets"],
        (" (" + ", ".join("%s x%d" % kv for kv in sorted(ev["gpu_codes"].items())) + ")") if ev["gpu_codes"] else "",
        sum(ev["hangs"].values()), ev["low_memory"]))
    if ev["hangs"]:
        L.append("  Hangs: " + ", ".join("%s x%d" % kv for kv in sorted(ev["hangs"].items())))
    if ev["low_memory_apps"]:
        L.append("  Largest users at low memory: " + ", ".join(sorted(ev["low_memory_apps"])))
    L.append("")
    L.append("Heavy processes (CPU seconds since each one started, memory now), and what started them:")
    for g in result["top"]:
        via = (" (chain: " + " > ".join(list(reversed(g["via"])) + [g["name"]]) + ")") if g["via"] else ""
        L.append("- %s x%d: CPU %ss, memory %s MB, started %s. %s: %s%s." % (
            g["name"], g["count"], g["cpu_s"], int(round(g["mem_mb"])), g["started"] or "?",
            ORIGIN_TEXT.get(g["origin"], g["origin"]), redact(g["detail"], user), via))
    f = result.get("files") or {}
    if f:
        L.append("")
        if f.get("onedrive_folders"):
            part = "" if f.get("onedrive_complete", True) else " (partial: the folder walk hit its time limit)"
            if f.get("onedrive"):
                L.append("Large Revit files saved into OneDrive since %s%s:" % (since or "today", part))
                for r in f["onedrive"][:10]:
                    L.append("  %s  %s MB  at %s" % (r["file"], r["mb"], r["saved"]))
            else:
                L.append("No large Revit file was saved into OneDrive since %s%s." % (since or "today", part))
        else:
            L.append("No OneDrive folder found.")
        if f.get("cache_gb") is not None:
            L.append("Revit cloud cache (CollaborationCache): %s GB%s." % (
                f["cache_gb"], "" if f.get("cache_complete", True) else " or more"))
        if f.get("temp_gb") is not None:
            L.append("%%TEMP%%: %s GB%s." % (f["temp_gb"], "" if f.get("temp_complete", True) else " or more"))
        if f.get("journals_read"):
            L.append("Revit journals read: %d, graphics device-removed lines: %d." % (
                f["journals_read"], f.get("journal_gpu_lines", 0)))
    L.append("")
    L.append("Safe next steps (you do them; this check changes nothing):")
    if result["actions"]:
        for a in result["actions"]:
            L.append("- " + a)
    else:
        L.append("- No clear cause found. Run the check again while the PC is slow.")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=0, help="also read events from this many days before today")
    ap.add_argument("--snapshot", help="analyze a saved snapshot JSON instead of this PC")
    ap.add_argument("--save-snapshot", help="write the raw snapshot JSON here (it holds command lines: keep it local)")
    ap.add_argument("--json", help="write the analysis as JSON here")
    ap.add_argument("--no-files", action="store_true", help="skip the OneDrive, cache, TEMP and journal reads")
    args = ap.parse_args(argv)
    try:
        if args.snapshot:
            with open(args.snapshot, encoding="utf-8-sig") as fh:
                snap = json.load(fh)
        else:
            if os.name != "nt":
                print("This check runs on Windows only.", file=sys.stderr)
                return 2
            try:
                snap = collect_snapshot(args.days)
            except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
                print("The process list could not be read: %s" % exc, file=sys.stderr)
                return 2
            if args.save_snapshot:
                with open(args.save_snapshot, "w", encoding="utf-8") as fh:
                    json.dump(snap, fh)
        if not snap.get("processes"):
            print("The process list is empty, so the check is not possible.", file=sys.stderr)
            return 2
        since = parse_time(snap.get("since")) or datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        files = None if args.no_files else collect_files(since)
        result = analyze(snap, files)
        print(render(result))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=1)
        return 0
    except Exception as exc:  # report, never crash silently
        print("slow_check error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

<#
.SYNOPSIS
  Find and explain recent Revit crashes and freezes. READ-ONLY.

.DESCRIPTION
  Reads, never writes (except the optional -Json file and -SupportPack zip):
    - Revit journals  %LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit <year>\Journals\journal.NNNN.txt
    - Revit crash dumps in the same Journals folder (journal.NNNN.*.dmp), listed only
    - Windows Application event log: Application Error (1000), Windows Error Reporting (1001),
      Application Hang (1002), .NET Runtime (1026) entries for Revit.exe
    - %LOCALAPPDATA%\Autodesk\CER (Autodesk crash reports) and %LOCALAPPDATA%\CrashDumps, listed only
    - Add-in manifests (*.addin) per user and per machine, to map a faulting module to an add-in
    - pyRevit logs under %APPDATA%\pyRevit\<year>, listed only
    - pyRevit agent run records under %APPDATA%\pyRevit\agent\runs and instance files under
      %APPDATA%\pyRevit\agent\instances (newest runs only, listed, never the script text)
  Works with Revit closed. Never kills or touches Revit. Never uploads anything.
  A journal that belongs to a Revit process that is still running is reported as IN_PROGRESS.

  Output is redacted by default: user name, user folders, project folders and cloud project
  names are replaced with placeholders. Model files are shown by file name only.

  Exit codes: 0 report done, 1 bad arguments or internal error, 2 nothing could be read.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File crash-doctor.ps1 -ListYears
  powershell -NoProfile -ExecutionPolicy Bypass -File crash-doctor.ps1 -Year 2026 -Days 14
  powershell -NoProfile -ExecutionPolicy Bypass -File crash-doctor.ps1 -Year 2026 -Json out.json -SupportPack "$env:USERPROFILE\Desktop"
#>
[CmdletBinding()]
param(
    [int]$Year,
    [int]$Days = 14,
    [string]$Journal,
    [string]$Json,
    [string]$SupportPack,
    [switch]$ListYears,
    # Test hooks: override every source so fixture tests never read real machine data.
    [string]$JournalRoot,
    [string[]]$AddinRoot,
    [string]$CerRoot,
    [string]$CrashDumpRoot,
    [string]$PyRevitRoot,
    [string]$AgentRoot,
    [string]$EventsFile,
    [string[]]$RunningRevit,   # "<year>=<yyyy-MM-ddTHH:mm:ss>" replaces Get-Process; "none" = no Revit running
    [switch]$NoRedact          # test only: proves the redaction test can fail
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Inv = [Globalization.CultureInfo]::InvariantCulture
$Now = Get-Date
$Since = $Now.AddDays(-[Math]::Abs($Days))

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$WorkDir = Join-Path $env:TEMP "am-revit-crash-doctor\$Stamp"
New-Item -ItemType Directory -Force $WorkDir | Out-Null
$LogFile = Join-Path $WorkDir 'crash-doctor.log'
try { Start-Transcript -Path $LogFile -Append | Out-Null } catch { }

if (-not $JournalRoot)   { $JournalRoot = Join-Path $env:LOCALAPPDATA 'Autodesk\Revit' }
if (-not $AddinRoot)     { $AddinRoot = @((Join-Path $env:APPDATA 'Autodesk\Revit\Addins'), 'C:\ProgramData\Autodesk\Revit\Addins') }
if (-not $CerRoot)       { $CerRoot = Join-Path $env:LOCALAPPDATA 'Autodesk\CER' }
if (-not $CrashDumpRoot) { $CrashDumpRoot = Join-Path $env:LOCALAPPDATA 'CrashDumps' }
if (-not $PyRevitRoot)   { $PyRevitRoot = Join-Path $env:APPDATA 'pyRevit' }
if (-not $AgentRoot)     { $AgentRoot = Join-Path $env:APPDATA 'pyRevit\agent' }

$Sources = New-Object System.Collections.Generic.List[object]
function Add-Source($name, $state, $detail) {
    # state: read | empty | not-present | could-not-read
    $Sources.Add([pscustomobject]@{ Source = $name; State = $state; Detail = $detail })
}
function Say($m)  { Write-Host $m }
function Done($code) {
    try { Stop-Transcript | Out-Null } catch { }
    exit $code
}

# ---------------------------------------------------------------- redaction
$script:UserName = $env:USERNAME
$script:Profile  = $env:USERPROFILE
function Redact([string]$s) {
    if ($NoRedact -or [string]::IsNullOrEmpty($s)) { return $s }
    $r = $s
    # Cloud model paths: keep only the file name.
    $r = [regex]::Replace($r, '(?i)CLD:\\\\[^"\]\s]*?\\([^\\"\]]+\.(rvt|rfa))', 'CLD:\\<cloud project>\$1')
    $r = [regex]::Replace($r, '(?i)CLD:\\\\(?!<)[^"\]\s]+', 'CLD:\\<cloud path>')
    $r = [regex]::Replace($r, '(?i)(Autodesk Docs|BIM 360)://[^"\]]*?/([^/"\]]+\.(rvt|rfa))', '$1://<project>/$2')
    $r = [regex]::Replace($r, '(?i)(Autodesk Docs|BIM 360)://[^"\]\s]+', '$1://<project>')
    # Network paths.
    $r = [regex]::Replace($r, '\\\\[^\\\s"\]]+\\[^"\]\r\n]*\\([^\\"\]\r\n]+)', '\\<server>\<path>\$1')
    $r = [regex]::Replace($r, '\\\\[A-Za-z0-9._-]+\\[^\s"\]]*', '\\<server>\<path>')
    # Local drive paths.
    $r = [regex]::Replace($r, '(?i)\b([A-Z]):\\((?:[^\\\r\n"<>|:\[\]]+\\)*)([^\\\r\n"<>|:\[\]\s,;]*)', {
        param($m)
        $full = $m.Value
        if ($script:Profile -and $full.StartsWith($script:Profile, [StringComparison]::OrdinalIgnoreCase)) {
            $rest = $full.Substring($script:Profile.Length)
            # Program folders under AppData are safe to show; document folders can name projects.
            if ($rest -match '(?i)^\\AppData\\' -or -not $m.Groups[2].Value) { return '%USERPROFILE%' + $rest }
            if (($rest.TrimStart('\') -split '\\').Count -le 1) { return '%USERPROFILE%' + $rest }
            return '%USERPROFILE%\<path>\' + $m.Groups[3].Value
        }
        if ($full -match '(?i)^[A-Z]:\\Users\\[^\\]+') { return ($full -replace '(?i)^([A-Z]):\\Users\\[^\\]+', '$1:\Users\<user>') }
        if ($full -match '(?i)^[A-Z]:\\(Program Files|Program Files \(x86\)|ProgramData|Windows)\\') { return $full }
        if ($full -match '(?i)^F:\\Ship') { return $full }   # Autodesk build-machine source paths in DBG lines
        return $m.Groups[1].Value + ':\<path>\' + $m.Groups[3].Value
    })
    $r = [regex]::Replace($r, '(?i)Rvt\.Attr\.Username:\s*\S+', 'Rvt.Attr.Username: <user>')
    # Autodesk account names often contain the Windows user name plus more text (e.g. in ModelSessionToken).
    $r = [regex]::Replace($r, "(?i)(User's Name|User Name|UserName)(\s*[:=]?\s*)[^\s,;""]+", '$1$2<user>')
    $r = [regex]::Replace($r, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '<email>')
    if ($script:UserName -and $script:UserName.Length -ge 4) {
        # No word boundaries: the name also appears glued to other text.
        $r = [regex]::Replace($r, '(?i)' + [regex]::Escape($script:UserName), '<user>')
    } elseif ($script:UserName) {
        $r = [regex]::Replace($r, '(?i)(?<![A-Za-z0-9])' + [regex]::Escape($script:UserName) + '(?![A-Za-z0-9])', '<user>')
    }
    if ($env:COMPUTERNAME) {
        $r = [regex]::Replace($r, '(?i)(?<![A-Za-z0-9])' + [regex]::Escape($env:COMPUTERNAME) + '(?![A-Za-z0-9])', '<computer>')
    }
    return $r
}
function Leaf([string]$p) {
    if (-not $p) { return $p }
    $p = $p.Trim().TrimEnd(']').Trim()
    $parts = $p -split '[\\/]'
    return [Uri]::UnescapeDataString($parts[$parts.Count - 1])
}

# ---------------------------------------------------------------- live Revit processes
$Running = New-Object System.Collections.Generic.List[object]
if ($RunningRevit) {
    foreach ($r in $RunningRevit) {
        if ($r -eq 'none') { continue }
        $kv = $r -split '=', 2
        $Running.Add([pscustomobject]@{ Year = [int]$kv[0]; Start = [datetime]::Parse($kv[1], $Inv); Pid = 0 })
    }
} else {
    foreach ($p in @(Get-Process Revit -ErrorAction SilentlyContinue)) {
        $y = 0; $st = $null
        try { $st = $p.StartTime } catch { }
        try { if ($p.Path -match 'Revit (20\d\d)') { $y = [int]$Matches[1] } } catch { }
        if ($st) { $Running.Add([pscustomobject]@{ Year = $y; Start = $st; Pid = $p.Id }) }
    }
}

# ---------------------------------------------------------------- journal parsing
$RxTime   = [regex]"^\s*'[A-Z] (\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2}\.\d{3});"
$RxCmd    = [regex]'^\s*Jrn\.Command\s+"([^"]*)"\s*,\s*"([^"]*)"'
$RxExtCmd = [regex]'Jrn\.RibbonEvent\s+"Execute external command:([^"]*)"'
$RxRam    = [regex]'RAM Statistics:\s+(\d+)\s*/\s*(\d+)\s+(\d+)=InUse\s+(\d+)=Peak'
$RxOpen   = [regex]'\[ISL\] On open, Adler Checksum: \S+ \[(.+)\]'
$RxBasic  = [regex]'Rvt\.Attr\.Worksharing:\s*(.*?)\s+Rvt\.Attr\.Username:.*?Rvt\.Attr\.CentralModelPath:\s*(.*?)\s+Rvt\.Attr\.RevitBuildVersion'
$RxAddin  = [regex]'Starting External (?:DB )?Application: (.*?), Class: (.*?), Vendor : (.*?)\((.*?)\), Assembly: (.*?\.dll)'
$RxCrash  = [regex]'(?i)Exception occurred|ExceptionCode=0x|SLOG \S+ \S+ \S+ >Crash|fatal error and cannot continue|unrecoverable error|An unrecoverable'
$RxError  = [regex]'(?i)Exception|fatal error|unrecoverable|DBG_WARN|DBG_ERR|API_FAILURE|Could not load|out of memory|Adlsdk Error|access (is )?denied|being used by another process'
$RxNoise  = [regex]'(?i)Invalid item in tooltip|addin file -pyRevit\.addin- in all user folder is duplicated|\.\.\.(Unhandled|DBG_WARNING) = '

function Open-Lines([string]$path) {
    # Revit keeps the live journal open for writing: share ReadWrite, stream line by line.
    $fs = New-Object IO.FileStream($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    return New-Object IO.StreamReader($fs, [Text.Encoding]::Default)
}

function Read-Journal([string]$path, [int]$year) {
    $s = [ordered]@{
        Journal = Leaf $path; Number = ''; Year = $year; Build = ''; Start = $null; End = $null
        Status = ''; StatusNote = ''; Models = (New-Object System.Collections.Generic.List[string])
        Worksharing = (New-Object System.Collections.Generic.List[string])
        CrashLine = 0; CrashTime = $null; ExceptionCode = ''; Antecedent = ''; UndoAfterCrash = (New-Object System.Collections.Generic.List[string])
        LastCommands = @(); LastRam = $null; MinRamAvail = $null
        Errors = (New-Object System.Collections.Generic.List[string])
        Addins = (New-Object System.Collections.Generic.List[object]); Dumps = @()
        Events = (New-Object System.Collections.Generic.List[object]); LineCount = 0; FileEnd = $null
        TailLines = @(); CleanExit = $false; ProgramTerminated = $false; FatalSeen = $false; LastLine = ''
    }
    if ($path -match 'journal\.(\d+)\.txt$') { $s.Number = $Matches[1] }
    $cmds = New-Object System.Collections.Generic.List[object]
    $tail = New-Object System.Collections.Generic.Queue[string]
    $prev = ''; $prev2 = ''; $n = 0; $lastTime = $null
    $errSeen = @{}
    $rd = Open-Lines $path
    try {
        while ($null -ne ($line = $rd.ReadLine())) {
            $n++
            $m = $RxTime.Match($line)
            if ($m.Success) {
                $t = [datetime]::MinValue
                if ([datetime]::TryParseExact($m.Groups[1].Value, 'dd-MMM-yyyy HH:mm:ss.fff', $Inv, 'None', [ref]$t)) {
                    if (-not $s.Start) { $s.Start = $t }
                    $lastTime = $t
                }
            }
            if ($n -le 12 -and $line -match "^' Build:\s*(\S+)") { $s.Build = $Matches[1] }
            if ($n -le 12 -and $line -match "^' Release:\s*(\S+)") { $s.Build = "$($Matches[1]) ($($s.Build))" }

            if ($s.CrashLine -eq 0) {
                $m = $RxCmd.Match($line)
                if ($m.Success) {
                    $raw = $m.Groups[2].Value
                    $k = $raw.LastIndexOf(',')
                    if ($k -ge 0) { $desc = $raw.Substring(0, $k).Trim(); $cid = $raw.Substring($k + 1).Trim() } else { $desc = $raw.Trim(); $cid = '' }
                    $txt = if ($desc -and $cid) { "$desc ($cid)" } elseif ($cid) { $cid } else { $desc }
                    $cmds.Add([pscustomobject]@{ Line = $n; Time = $lastTime; Text = $txt; External = '' })
                }
                $m = $RxExtCmd.Match($line)
                if ($m.Success) {
                    $raw = $m.Groups[1].Value
                    $tok = @($raw -split '%' | Where-Object { $_ -and $_ -notmatch '^CustomCtrl_' })
                    $label = ($tok | Select-Object -First 3) -join ' > '
                    $label = $label -replace ':[^>]*$', ''
                    $tab = if ($tok.Count -gt 0) { $tok[0] } else { $raw }
                    $cmds.Add([pscustomobject]@{ Line = $n; Time = $lastTime; Text = "add-in command: $label"; External = $tab })
                }
                $m = $RxRam.Match($line)
                if ($m.Success) {
                    $ram = [pscustomobject]@{ AvailMB = [int]$m.Groups[1].Value; TotalMB = [int]$m.Groups[2].Value; RevitInUseMB = [int]$m.Groups[3].Value; RevitPeakMB = [int]$m.Groups[4].Value; Time = $lastTime }
                    $s.LastRam = $ram
                    if (-not $s.MinRamAvail -or $ram.AvailMB -lt $s.MinRamAvail.AvailMB) { $s.MinRamAvail = $ram }
                }
                if ($RxCrash.IsMatch($line)) {
                    $s.CrashLine = $n; $s.CrashTime = $(if ($RxTime.IsMatch($line)) { $lastTime } else { $null })
                    if ($prev -match "ANTECEDENT" -or $prev2 -match "ANTECEDENT") { $s.Antecedent = ($prev -replace "^\s*'\s*", '').Trim() }
                }
            } else {
                if (-not $s.CrashTime -and $m.Success -and $RxTime.IsMatch($line)) { $s.CrashTime = $lastTime }
                if (-not $s.ExceptionCode -and $line -match 'ExceptionCode=(0x[0-9a-fA-F]+)') { $s.ExceptionCode = $Matches[1] }
                if ($s.UndoAfterCrash.Count -lt 5 -and $line -match 'Undoing transaction:\s*(.+?)\s*$') {
                    if (-not $s.UndoAfterCrash.Contains($Matches[1])) { $s.UndoAfterCrash.Add($Matches[1]) }
                }
            }
            if ($s.CrashLine -gt 0 -and -not $s.ExceptionCode -and $line -match 'ExceptionCode=(0x[0-9a-fA-F]+)') { $s.ExceptionCode = $Matches[1] }
            if ($line -match 'program terminated') { $s.ProgramTerminated = $true }
            if ($line -match '(?i)fatal error and cannot continue|unrecoverable error|SLOG \S+ \S+ \S+ >Crash') { $s.FatalSeen = $true }
            if ($line -match 'finished recording journal file') { $s.CleanExit = $true }

            $m = $RxOpen.Match($line)
            if ($m.Success) { $leaf = Leaf $m.Groups[1].Value; if (-not $s.Models.Contains($leaf)) { $s.Models.Add($leaf) } }
            $m = $RxBasic.Match($line)
            if ($m.Success) {
                $ws = $m.Groups[1].Value.Trim(); $cp = $m.Groups[2].Value.Trim()
                $kind = $ws
                if ($cp -match '^\\\\') { $kind = "$ws, central model on a network path" }
                elseif ($cp -match '(?i)^(Autodesk Docs|BIM 360|CLD)') { $kind = "$ws, cloud model" }
                if ($cp -match '\.(rvt|rfa)$') { $leaf = Leaf $cp; if (-not $s.Models.Contains($leaf)) { $s.Models.Add($leaf) } }
                if ($ws -and $ws -ne 'Not enabled' -and -not $s.Worksharing.Contains($kind)) { $s.Worksharing.Add($kind) }
            }
            $m = $RxAddin.Match($line)
            if ($m.Success) {
                $vend = $m.Groups[3].Value.Trim(); $cls = $m.Groups[2].Value.Trim()
                if ($m.Groups[4].Value -match '(?i)autodesk' -or $cls -match '^(Autodesk|Adsk)\.') { $vend = 'ADSK' }
                $s.Addins.Add([pscustomobject]@{ Name = $m.Groups[1].Value.Trim(); Class = $cls; Vendor = $vend; Assembly = $m.Groups[5].Value.Trim() })
            }
            if ($RxError.IsMatch($line) -and -not $RxNoise.IsMatch($line)) {
                $key = ($line.Trim() -replace '\d', '#')
                if ($key.Length -gt 90) { $key = $key.Substring(0, 90) }
                if (-not $errSeen.ContainsKey($key)) {
                    $errSeen[$key] = 1
                    $txt = $line.Trim(); if ($txt.Length -gt 220) { $txt = $txt.Substring(0, 220) + '...' }
                    $s.Errors.Add("line ${n}: $txt")
                }
            }
            if ($line.Trim()) { $s.LastLine = $line.Trim() }
            $tail.Enqueue($line); if ($tail.Count -gt 40) { [void]$tail.Dequeue() }
            $prev2 = $prev; $prev = $line
        }
    } finally { $rd.Close() }
    $s.LineCount = $n
    $s.End = $lastTime
    $s.FileEnd = (Get-Item -LiteralPath $path).LastWriteTime
    $s.TailLines = @($tail.ToArray())
    if ($s.CrashLine -gt 0 -and -not $s.CrashTime) { $s.CrashTime = $lastTime }
    # Collapse repeats (Revit writes some commands 2-3 times), then keep the last 15.
    $dedup = New-Object System.Collections.Generic.List[object]
    foreach ($c in $cmds) {
        $p = if ($dedup.Count) { $dedup[$dedup.Count - 1] } else { $null }
        if ($p -and $p.Text -eq $c.Text -and $c.Time -and $p.Time -and ($c.Time - $p.Time).TotalSeconds -le 5) { $p.Count++; continue }
        $c | Add-Member -NotePropertyName Count -NotePropertyValue 1
        $dedup.Add($c)
    }
    $s.LastCommands = @($dedup | Select-Object -Last 15)
    return $s
}

function Set-Status($s) {
    $live = $null
    if ($s.Start) {
        foreach ($p in $Running) {
            if ($p.Year -and $s.Year -and $p.Year -ne $s.Year) { continue }
            $d = [Math]::Abs(($p.Start - $s.Start).TotalSeconds)
            if ($d -le 120 -and (-not $live -or $d -lt $live.D)) { $live = [pscustomobject]@{ D = $d; P = $p } }
        }
    }
    if ($live) {
        $s.Status = 'IN_PROGRESS'
        $pidTxt = if ($live.P.Pid) { "pid $($live.P.Pid)" } else { 'a running Revit' }
        $s.StatusNote = "Revit is still running ($pidTxt started $($live.P.Start.ToString('yyyy-MM-dd HH:mm:ss'))). This session is not finished, so it is not a crash."
    } elseif ($s.FatalSeen -or ($s.CrashLine -gt 0 -and -not $s.CleanExit) -or ($s.ProgramTerminated -and -not $s.CleanExit) -or @($s.Dumps).Count -gt 0) {
        $s.Status = 'CRASH'
        $why = @()
        if ($s.CrashLine -gt 0) { $why += "crash text at line $($s.CrashLine)" }
        if ($s.ProgramTerminated -and -not $s.CleanExit) { $why += "'program terminated' without a normal close" }
        if (@($s.Dumps).Count -gt 0) { $why += "Revit wrote $(@($s.Dumps).Count) crash dump file(s)" }
        $s.StatusNote = 'Revit crashed: ' + ($why -join '; ') + '.'
    } elseif ($s.CleanExit) {
        $s.Status = 'CLEAN_EXIT'; $s.StatusNote = 'Revit closed normally.'
        if ($s.CrashLine -gt 0) { $s.StatusNote += " An error was logged at line $($s.CrashLine), but Revit continued." }
    } elseif ($s.LastLine -match 'Adlsdk Error' -and $s.Models.Count -eq 0) {
        $s.Status = 'LICENSE_ABORT'
        $s.StatusNote = 'The session stopped at the license check, before any model opened. Revit did not crash in a model.'
    } else {
        $s.Status = 'ABRUPT_END'
        $s.StatusNote = 'The journal stops with no normal close and no crash text. Possible causes: a freeze that was ended in Task Manager, a forced close, a Windows restart, or a crash with no report.'
        if ($s.Models.Count -eq 0 -and @($s.LastCommands).Count -eq 0) { $s.StatusNote += ' It stopped during start-up, before any model opened.' }
    }
}

# ---------------------------------------------------------------- events
function Convert-Event($provider, $id, $time, $message, $props) {
    $e = [ordered]@{ Time = $time; Provider = $provider; Id = $id; Kind = 'OTHER'; AppVersion = ''; Module = ''; ModuleVersion = ''; ModulePath = ''; ExceptionCode = ''; Detail = ''; Session = '' }
    $pv = @($props)
    switch ($id) {
        1000 {
            $e.Kind = 'CRASH'
            if ($pv.Count -ge 7) {
                $e.AppVersion = "$($pv[1])"; $e.Module = "$($pv[3])"; $e.ModuleVersion = "$($pv[4])"
                $code = $pv[6]
                if ($code -is [int] -or $code -is [long] -or $code -is [uint32]) { $e.ExceptionCode = '0x{0:x8}' -f ([uint32]([int64]$code -band 0xFFFFFFFF)) } else { $e.ExceptionCode = "$code"; if ($e.ExceptionCode -match '^[0-9a-fA-F]{8}$') { $e.ExceptionCode = '0x' + $e.ExceptionCode } }
                if ($pv.Count -ge 12) { $e.ModulePath = "$($pv[11])" }
            } else {
                if ($message -match 'Faulting module name:\s*([^,\r\n]+),\s*version:\s*([^,\r\n]+)') { $e.Module = $Matches[1].Trim(); $e.ModuleVersion = $Matches[2].Trim() }
                if ($message -match 'Exception code:\s*(0x[0-9a-fA-F]+)') { $e.ExceptionCode = $Matches[1] }
                if ($message -match 'Faulting module path:\s*([^\r\n]+)') { $e.ModulePath = $Matches[1].Trim() }
                if ($message -match 'Faulting application name:\s*[^,]+,\s*version:\s*([^,\r\n]+)') { $e.AppVersion = $Matches[1].Trim() }
            }
        }
        1001 {
            $name = ''
            if ($pv.Count -ge 3) { $name = "$($pv[2])" } elseif ($message -match 'Event Name:\s*(\S+)') { $name = $Matches[1] }
            $p = @{}
            for ($i = 1; $i -le 10; $i++) {
                if ($pv.Count -ge (5 + $i)) { $p[$i] = "$($pv[4 + $i])" }
                elseif ($message -match ("(?m)^P$i" + ':\s*(.*?)\s*$')) { $p[$i] = $Matches[1] }
            }
            $e.AppVersion = $p[2]; $e.Detail = "WER event $name"
            if ($name -match '^(APPCRASH|BEX|BEX64|CLR20r3|MoAppCrash)') {
                $e.Kind = 'CRASH'
                if ($name -match '^CLR20r3') { $e.Detail += " (.NET error: $($p[9]))" }
                else { $e.Module = $p[4]; $e.ModuleVersion = $p[5]; $e.ExceptionCode = $p[7] }
            } elseif ($name -match '(?i)Hang') { $e.Kind = 'HANG' }
            elseif ($name -match '(?i)RADAR_PRE_LEAK') { $e.Kind = 'MEMORY_LEAK_WARNING'; $e.Detail += ' (Windows saw Revit memory use grow fast; this is not a crash)' }
            else { $e.Kind = 'REPORT' }
        }
        1002 { $e.Kind = 'HANG'; if ($pv.Count -ge 2) { $e.AppVersion = "$($pv[1])" }; $e.Detail = 'Revit stopped responding and was closed.' }
        1026 {
            $e.Kind = 'DOTNET_ERROR'
            if ($message -match 'Exception Info:\s*([\w.`]+)') { $e.Detail = $Matches[1] }
            $frames = [regex]::Matches($message, '(?m)^\s*at\s+([\w.`<>]+)\.')
            $ns = @($frames | ForEach-Object { ($_.Groups[1].Value -split '\.')[0] } | Where-Object { $_ -notmatch '^(System|Microsoft|MS|Autodesk|UIFramework|UIFrameworkServices|AdWindows|Xceed)$' } | Select-Object -Unique)
            if ($ns.Count -gt 0) { $e.Module = $ns[0]; $e.Detail += " (code namespace: $($ns -join ', '))" }
        }
    }
    return [pscustomobject]$e
}

$Events = New-Object System.Collections.Generic.List[object]
$EventsRead = $false
if ($EventsFile) {
    try {
        $raw = Get-Content -LiteralPath $EventsFile -Raw | ConvertFrom-Json
        foreach ($r in @($raw)) {
            $Events.Add((Convert-Event $r.Provider ([int]$r.Id) ([datetime]::Parse($r.Time, $Inv)) "$($r.Message)" @($r.Properties)))
        }
        $EventsRead = $true
        Add-Source 'Windows event log (fixture file)' 'read' "$($Events.Count) Revit event(s)"
    } catch { Add-Source 'Windows event log (fixture file)' 'could-not-read' $_.Exception.Message }
} else {
    try {
        $raw = @(Get-WinEvent -FilterHashtable @{ LogName = 'Application'; StartTime = $Since; Id = 1000, 1001, 1002, 1026 } -ErrorAction Stop)
        $EventsRead = $true
        foreach ($ev in $raw) {
            if ($ev.ProviderName -notin @('Application Error', 'Windows Error Reporting', 'Application Hang', '.NET Runtime')) { continue }
            $msg = "$($ev.Message)"
            $props = @($ev.Properties | ForEach-Object { $_.Value })
            if (-not ($msg -match '(?i)Revit\.exe' -or (@($props) -join ' ') -match '(?i)Revit\.exe')) { continue }
            $Events.Add((Convert-Event $ev.ProviderName $ev.Id $ev.TimeCreated $msg $props))
        }
        Add-Source "Windows event log (Application, last $Days days)" 'read' "$($Events.Count) Revit event(s)"
    } catch {
        if ($_.FullyQualifiedErrorId -match 'NoMatchingEventsFound' -or $_.Exception.Message -match 'No events were found') {
            $EventsRead = $true
            Add-Source "Windows event log (Application, last $Days days)" 'read' '0 Revit events'
        } else {
            Add-Source 'Windows event log' 'could-not-read' $_.Exception.Message
        }
    }
}

# ---------------------------------------------------------------- journal discovery
$YearDirs = @()
$JournalFiles = New-Object System.Collections.Generic.List[object]
$JournalsRead = 0
if ($Journal) {
    if (Test-Path -LiteralPath $Journal) {
        $y = 0; if ($Journal -match 'Revit (20\d\d)') { $y = [int]$Matches[1] }
        if ($Year) { $y = $Year }
        $JournalFiles.Add([pscustomobject]@{ Path = (Resolve-Path -LiteralPath $Journal).Path; Year = $y; Dir = (Split-Path -Parent (Resolve-Path -LiteralPath $Journal).Path) })
    } else { Add-Source "journal $(Leaf $Journal)" 'could-not-read' 'file not found' }
} else {
    if (-not (Test-Path -LiteralPath $JournalRoot)) {
        Add-Source 'Revit journals' 'not-present' 'Revit journal folder not found'
    } else {
        try {
            $YearDirs = @(Get-ChildItem -LiteralPath $JournalRoot -Directory -ErrorAction Stop | Where-Object { $_.Name -match '^Autodesk Revit (20\d\d)$' })
        } catch { Add-Source 'Revit journals' 'could-not-read' $_.Exception.Message }
        if ($YearDirs.Count -eq 0) { Add-Source 'Revit journals' 'not-present' 'no "Autodesk Revit <year>" folders' }
    }
}

if ($ListYears) {
    Say '[crash-doctor] Revit years with journals:'
    $rows = @()
    foreach ($d in $YearDirs) {
        $y = [int]($d.Name -replace '\D', '')
        $jd = Join-Path $d.FullName 'Journals'
        $files = @(Get-ChildItem -LiteralPath $jd -Filter 'journal.*.txt' -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^journal\.\d+\.txt$' })
        $recent = @($files | Where-Object { $_.LastWriteTime -ge $Since })
        $newest = ($files | Sort-Object LastWriteTime | Select-Object -Last 1)
        $rows += [pscustomobject]@{ Year = $y; Recent = $recent.Count; Total = $files.Count; Newest = if ($newest) { $newest.LastWriteTime } else { $null } }
    }
    $rows = @($rows | Sort-Object Newest -Descending)
    foreach ($r in $rows) {
        $nw = if ($r.Newest) { $r.Newest.ToString('yyyy-MM-dd HH:mm') } else { '-' }
        Say ("  Revit {0}: {1} session(s) in the last {2} days, {3} journal(s) in total, newest {4}" -f $r.Year, $r.Recent, $Days, $r.Total, $nw)
    }
    if ($rows.Count -eq 0) { Say '  none found'; Done 2 }
    Done 0
}

foreach ($d in $YearDirs) {
    $y = [int]($d.Name -replace '\D', '')
    if ($Year -and $y -ne $Year) { continue }
    $jd = Join-Path $d.FullName 'Journals'
    try {
        $files = @(Get-ChildItem -LiteralPath $jd -ErrorAction Stop | Where-Object { $_.Name -match '^journal\.\d+\.txt$' -and $_.LastWriteTime -ge $Since })
        foreach ($f in $files) { $JournalFiles.Add([pscustomobject]@{ Path = $f.FullName; Year = $y; Dir = $jd }) }
        if ($files.Count -eq 0) { Add-Source "Revit $y journals" 'empty' "no journal written in the last $Days days" }
    } catch { Add-Source "Revit $y journals" 'could-not-read' $_.Exception.Message }
}
if ($Year -and -not $Journal -and -not ($YearDirs | Where-Object { $_.Name -eq "Autodesk Revit $Year" })) {
    Add-Source "Revit $Year journals" 'not-present' "no journal folder for Revit $Year"
}

# ---------------------------------------------------------------- add-in manifests
$AddinFiles = New-Object System.Collections.Generic.List[object]
foreach ($root in $AddinRoot) {
    if (-not (Test-Path -LiteralPath $root)) { Add-Source "add-in manifests ($(Redact $root))" 'not-present' ''; continue }
    try {
        $dirs = @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction Stop | Where-Object { -not $Year -or $_.Name -eq "$Year" })
        $cnt = 0
        foreach ($yd in $dirs) {
            foreach ($af in @(Get-ChildItem -LiteralPath $yd.FullName -Filter '*.addin' -ErrorAction SilentlyContinue)) {
                try {
                    $addinXml = New-Object Xml.XmlDocument
                    $addinXml.LoadXml([IO.File]::ReadAllText($af.FullName))
                    foreach ($a in @($addinXml.RevitAddIns.AddIn)) {
                        if (-not $a) { continue }
                        $asm = "$($a.Assembly)".Trim()
                        if ($asm -and -not [IO.Path]::IsPathRooted($asm)) { $asm = [IO.Path]::GetFullPath((Join-Path $yd.FullName $asm)) }
                        $AddinFiles.Add([pscustomobject]@{ Year = $yd.Name; Manifest = $af.Name; Name = "$($a.Name)".Trim(); Vendor = "$($a.VendorId)".Trim(); Assembly = $asm; Class = "$($a.FullClassName)".Trim() })
                        $cnt++
                    }
                } catch { Add-Source "add-in manifest $($af.Name)" 'could-not-read' $_.Exception.Message }
            }
        }
        Add-Source "add-in manifests ($(Redact $root))" 'read' "$cnt add-in entries"
    } catch { Add-Source "add-in manifests ($(Redact $root))" 'could-not-read' $_.Exception.Message }
}

# ---------------------------------------------------------------- dumps, CER, pyRevit
$JournalDumps = New-Object System.Collections.Generic.List[object]
$jdirs = @($JournalFiles | Select-Object -ExpandProperty Dir -Unique)
if (-not $Journal) { foreach ($d in $YearDirs) { $jd = Join-Path $d.FullName 'Journals'; if ($jdirs -notcontains $jd -and (Test-Path $jd)) { $jdirs += $jd } } }
foreach ($jd in $jdirs) {
    try {
        foreach ($f in @(Get-ChildItem -LiteralPath $jd -Filter 'journal.*.dmp' -ErrorAction Stop | Where-Object { $_.LastWriteTime -ge $Since })) {
            $num = if ($f.Name -match '^journal\.(\d+)\.') { $Matches[1] } else { '' }
            $JournalDumps.Add([pscustomobject]@{ Name = $f.Name; Number = $num; Time = $f.LastWriteTime; SizeMB = [Math]::Round($f.Length / 1MB, 1); Folder = (Redact $jd) })
        }
    } catch { Add-Source 'Revit crash dumps (Journals folder)' 'could-not-read' $_.Exception.Message }
}
Add-Source 'Revit crash dumps (Journals folder)' 'read' "$($JournalDumps.Count) dump file(s) in the last $Days days"

$OtherDumps = New-Object System.Collections.Generic.List[object]
if (Test-Path -LiteralPath $CrashDumpRoot) {
    try {
        foreach ($f in @(Get-ChildItem -LiteralPath $CrashDumpRoot -Filter 'Revit*.dmp' -ErrorAction Stop | Where-Object { $_.LastWriteTime -ge $Since })) {
            $OtherDumps.Add([pscustomobject]@{ Name = $f.Name; Time = $f.LastWriteTime; SizeMB = [Math]::Round($f.Length / 1MB, 1) })
        }
        Add-Source 'Windows crash dumps (CrashDumps)' 'read' "$($OtherDumps.Count) Revit dump(s)"
    } catch { Add-Source 'Windows crash dumps (CrashDumps)' 'could-not-read' $_.Exception.Message }
} else { Add-Source 'Windows crash dumps (CrashDumps)' 'not-present' '' }

$CerReports = New-Object System.Collections.Generic.List[object]
if (Test-Path -LiteralPath $CerRoot) {
    try {
        # One report = one folder that holds a minidump. The product is named only in the
        # parent folder's cer.log, so look for "Revit" there.
        # PS 5.1: -Include is unreliable with -LiteralPath, so filter by name here.
        # A Revit report folder holds journal.NNNN.NNNN.dmp.zip (the Revit dump plus its journal number).
        $files = @(Get-ChildItem -LiteralPath $CerRoot -Recurse -File -ErrorAction Stop | Where-Object { $_.Name -match '(?i)^minidump.*\.zip$|\.dmp(\.zip)?$|^rawdata-t1\.pb$' -and $_.LastWriteTime -ge $Since })
        foreach ($g in ($files | Group-Object { $_.Directory.FullName })) {
            $dir = $g.Group[0].Directory
            $t = ($g.Group | Sort-Object LastWriteTime | Select-Object -First 1).LastWriteTime
            $product = 'unknown product'; $jn = ''
            $jdump = $g.Group | Where-Object { $_.Name -match '^journal\.(\d+)\.\d+\.dmp' } | Select-Object -First 1
            if ($jdump -and $jdump.Name -match '^journal\.(\d+)\.') { $product = 'Revit'; $jn = $Matches[1] }
            else {
                $log = Join-Path $dir.Parent.FullName 'cer.log'
                if (Test-Path -LiteralPath $log) { if (Select-String -LiteralPath $log -Pattern '\\Revit 20\d\d\\' -List -Quiet) { $product = 'Revit' } else { $product = 'not Revit' } }
            }
            $CerReports.Add([pscustomobject]@{ Report = $dir.Name; Time = $t; Product = $product; JournalNumber = $jn; Session = '' })
        }
        $rv = @($CerReports | Where-Object { $_.Product -eq 'Revit' }).Count
        Add-Source 'Autodesk crash reports (CER)' 'read' "$($CerReports.Count) report(s) with a dump, $rv of them name Revit"
    } catch { Add-Source 'Autodesk crash reports (CER)' 'could-not-read' $_.Exception.Message }
} else { Add-Source 'Autodesk crash reports (CER)' 'not-present' '' }

$PyLogs = @()
if (Test-Path -LiteralPath $PyRevitRoot) {
    try {
        $PyLogs = @(Get-ChildItem -LiteralPath $PyRevitRoot -Recurse -Filter '*.log' -ErrorAction Stop | Where-Object { $_.LastWriteTime -ge $Since })
        Add-Source 'pyRevit logs' 'read' "$($PyLogs.Count) log file(s)"
    } catch { Add-Source 'pyRevit logs' 'could-not-read' $_.Exception.Message }
}

# ---------------------------------------------------------------- pyRevit agent runs
# The agent writes one response.json per run under runs\<date>-<time>-<run_id>. Read only the
# newest records, and only their status, error and run name. Never print script text: a record
# may carry the full script, so a script field is used only when it looks like a short path.
$AgentRuns = New-Object System.Collections.Generic.List[object]
$AgentInstances = 0
if (-not (Test-Path -LiteralPath $AgentRoot)) {
    Add-Source 'pyRevit agent runs' 'not-present' 'no pyRevit agent folder'
} else {
    try {
        $runsDir = Join-Path $AgentRoot 'runs'
        $recs = @()
        if (Test-Path -LiteralPath $runsDir) {
            $recs = @(Get-ChildItem -LiteralPath $runsDir -Filter 'response.json' -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $Since } | Sort-Object LastWriteTime -Descending)
        }
        foreach ($rec in @($recs | Select-Object -First 5)) {
            $runId = (Split-Path -Parent $rec.FullName | Split-Path -Leaf)
            $status = ''; $err = ''; $scriptName = ''
            try {
                $rj = [IO.File]::ReadAllText($rec.FullName) | ConvertFrom-Json
                $status = "$($rj.status)"
                $err = "$($rj.error)"
                foreach ($k in 'tool', 'name') { if ($rj.$k) { $scriptName = "$($rj.$k)"; break } }
                if (-not $scriptName -and $rj.script) {
                    $sv = "$($rj.script)"
                    if ($sv -notmatch "`n" -and $sv.Length -le 200 -and $sv -match '(?i)\.py$|\\|/') { $scriptName = Leaf $sv }
                }
            } catch { $status = 'unreadable' }
            $AgentRuns.Add([pscustomobject]@{ Time = $rec.LastWriteTime; Run = $runId; Status = $status; Error = $err; Script = $scriptName })
        }
        Add-Source 'pyRevit agent runs' 'read' "$($AgentRuns.Count) run record(s) in the last $Days days"
        $instDir = Join-Path $AgentRoot 'instances'
        if (Test-Path -LiteralPath $instDir) {
            $AgentInstances = @(Get-ChildItem -LiteralPath $instDir -Filter '*.json' -ErrorAction SilentlyContinue).Count
        }
        Add-Source 'pyRevit agent instance files' 'read' "$AgentInstances instance file(s)"
    } catch { Add-Source 'pyRevit agent runs' 'could-not-read' $_.Exception.Message }
}

# ---------------------------------------------------------------- parse journals
$Sessions = New-Object System.Collections.Generic.List[object]
foreach ($jf in ($JournalFiles | Sort-Object Path)) {
    try {
        $s = Read-Journal $jf.Path $jf.Year
        $s.Dumps = @($JournalDumps | Where-Object { $_.Number -and $_.Number -eq $s.Number -and (Redact $jf.Dir) -eq $_.Folder })
        Set-Status $s
        $Sessions.Add($s)
        $JournalsRead++
    } catch {
        Add-Source "journal $(Leaf $jf.Path)" 'could-not-read' $_.Exception.Message
    }
}
if ($JournalFiles.Count -gt 0) { Add-Source 'Revit journals' ($(if ($JournalsRead -gt 0) { 'read' } else { 'could-not-read' })) "$JournalsRead of $($JournalFiles.Count) journal(s) read" }

# Dumps whose journal is missing (Revit sometimes keeps only an .abbrev copy).
$OrphanDumps = @($JournalDumps | Where-Object { $d = $_; -not ($Sessions | Where-Object { $_.Number -eq $d.Number }) })

# ---------------------------------------------------------------- match events to sessions
foreach ($e in $Events) {
    $ey = 0
    if ($e.AppVersion -match '^(\d{2})\.') { $ey = 2000 + [int]$Matches[1] }
    $best = $null
    foreach ($s in $Sessions) {
        if (-not $s.Start) { continue }
        if ($ey -and $s.Year -and $ey -ne $s.Year) { continue }
        $end = if ($s.Status -eq 'IN_PROGRESS') { $Now } else { @($s.End, $s.FileEnd | Where-Object { $_ } | Sort-Object | Select-Object -Last 1)[0] }
        if ($e.Time -ge $s.Start.AddMinutes(-1) -and $e.Time -le $end.AddMinutes(3)) {
            if (-not $best -or $s.Start -gt $best.Start) { $best = $s }
        }
    }
    if ($best) { $e.Session = $best.Journal; $best.Events.Add($e) }
}
# A Windows crash or hang event inside a session that ended abruptly confirms the crash.
foreach ($s in ($Sessions | Where-Object { $_.Status -eq 'ABRUPT_END' })) {
    $ce = @($s.Events | Where-Object { $_.Kind -in 'CRASH', 'DOTNET_ERROR' }) | Select-Object -First 1
    $he = @($s.Events | Where-Object { $_.Kind -eq 'HANG' }) | Select-Object -First 1
    if ($ce) { $s.Status = 'CRASH'; $s.StatusNote = "Revit crashed: Windows recorded a Revit crash at $($ce.Time.ToString('yyyy-MM-dd HH:mm:ss'))." }
    elseif ($he) { $s.StatusNote = "Revit froze: Windows recorded that Revit stopped responding at $($he.Time.ToString('yyyy-MM-dd HH:mm:ss')), and it was closed." }
}
foreach ($r in ($CerReports | Where-Object { $_.Product -eq 'Revit' })) {
    foreach ($s in $Sessions) {
        if (-not $s.Start -or $s.Status -eq 'IN_PROGRESS') { continue }
        $end = @($s.End, $s.FileEnd | Where-Object { $_ } | Sort-Object | Select-Object -Last 1)[0]
        $inWindow = ($r.Time -ge $s.Start -and $r.Time -le $end.AddMinutes(10))
        if ($inWindow -and (-not $r.JournalNumber -or $r.JournalNumber -eq $s.Number)) { $r.Session = $s.Journal }
    }
}

# ---------------------------------------------------------------- classification
$RxGraphics = '(?i)^(nvoglv|nvwgf2um|nvd3dum|nvldumd|nvcuda|atig6|atio6|aticfx|atiumd|atidxx|amdxc|amdxx|amdihk|igd|igc|ig\d|iglhxa|d3d1[012]|d3d9|dxgi|dxcore|opengl32|vulkan|GraphicsDevice|DirectX)'
$RxRuntime  = '(?i)^(ntdll|kernelbase|kernel32|ucrtbase|msvcp|vcruntime|clr|coreclr|combase|user32|win32u)'

function Get-ThirdParty($s) {
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($a in $s.Addins) { if ($a.Vendor -notmatch '^(ADSK|Autodesk)$' -and $a.Assembly -notmatch '(?i)\\Autodesk\\Revit 20\d\d\\') { $list.Add($a) } }
    foreach ($a in $AddinFiles) {
        if ($s.Year -and $a.Year -ne "$($s.Year)") { continue }
        if ($a.Vendor -match '^(ADSK|Autodesk)$') { continue }
        if (-not ($list | Where-Object { (Leaf $_.Assembly) -eq (Leaf $a.Assembly) })) { $list.Add($a) }
    }
    return $list
}

function Classify($s) {
    $c = New-Object System.Collections.Generic.List[object]
    function Add-C($cls, $conf, $ev) { $c.Add([pscustomobject]@{ Class = $cls; Confidence = $conf; Evidence = $ev }) }
    $third = Get-ThirdParty $s
    $addinName = ''
    $crashEvents = @($s.Events | Where-Object { $_.Kind -in 'CRASH', 'DOTNET_ERROR' })
    $hasMarker = ($s.Status -eq 'CRASH') -or (@($s.Events | Where-Object { $_.Kind -in 'CRASH', 'HANG', 'DOTNET_ERROR' }).Count -gt 0)
    foreach ($e in $crashEvents) {
        $mod = "$($e.Module)"; if (-not $mod) { continue }
        $modLeaf = Leaf $mod; $modBase = [IO.Path]::GetFileNameWithoutExtension($modLeaf)
        $ev = "Windows event $($e.Time.ToString('yyyy-MM-dd HH:mm:ss')): faulting module $modLeaf $($e.ModuleVersion) $($e.ExceptionCode)".Trim()
        $hit = $third | Where-Object {
            $al = Leaf $_.Assembly; $ab = [IO.Path]::GetFileNameWithoutExtension($al)
            ($al -and $al -ieq $modLeaf) -or ($ab -and $ab -ieq $modBase) -or
            ($_.Class -and ($_.Class -split '\.')[0] -ieq $modBase) -or
            ($e.ModulePath -and $_.Assembly -and (Split-Path -Parent $_.Assembly) -and $e.ModulePath.StartsWith((Split-Path -Parent $_.Assembly), [StringComparison]::OrdinalIgnoreCase))
        } | Select-Object -First 1
        if ($hit) { Add-C 'ADDIN' 3 "$ev; this file belongs to the add-in '$($hit.Name)' ($(Leaf $hit.Assembly))"; $addinName = $hit.Name }
        elseif ($modLeaf -match $RxGraphics) { Add-C 'GRAPHICS' 3 "$ev; this is a graphics driver or DirectX file" }
        elseif ($e.ModulePath -match '(?i)\\Autodesk\\Revit 20\d\d\\' -or $modLeaf -match '(?i)^(Revit|RevitDB|RevitUI|RevitAPI|Graphics|AdWindows|ADSK|AdskRcp|DBG|Foundation|Geom|Math|UIFramework)') { Add-C 'REVIT_CORE' 2 "$ev; this is a Revit program file" }
        elseif ($modLeaf -match $RxRuntime) { Add-C 'UNKNOWN' 1 "$ev; this is a general Windows or .NET file, so the real cause is earlier in the chain" }
        else { Add-C 'UNKNOWN' 1 $ev }
    }
    # Memory: last reading before the crash (or end), and the lowest reading in the session.
    # Only the last reading before the crash counts as strong evidence. A low reading earlier
    # in the session (Windows can free memory again) is weak evidence only.
    $ram = $s.LastRam
    if ($ram) {
        $ratio = if ($ram.TotalMB) { $ram.AvailMB / $ram.TotalMB } else { 1 }
        $ev = "last memory reading before the end: $($ram.AvailMB) MB of $($ram.TotalMB) MB RAM free, Revit used $($ram.RevitInUseMB) MB (peak $($ram.RevitPeakMB) MB)"
        if ($ram.AvailMB -lt 1024 -or $ratio -lt 0.05) { Add-C 'MEMORY' 3 $ev }
        elseif ($ram.AvailMB -lt 2048 -or $ratio -lt 0.12) { Add-C 'MEMORY' 2 $ev }
    }
    $low = $s.MinRamAvail
    if ($low -and $low -ne $ram -and $low.TotalMB -and ($low.AvailMB -lt 1024 -or $low.AvailMB / $low.TotalMB -lt 0.05)) {
        $tt = if ($low.Time) { $low.Time.ToString('yyyy-MM-dd HH:mm') } else { 'earlier' }
        Add-C 'MEMORY' 1 "free RAM was low earlier in the session ($tt): $($low.AvailMB) MB of $($low.TotalMB) MB"
    }
    foreach ($e in @($s.Events | Where-Object { $_.Kind -eq 'MEMORY_LEAK_WARNING' })) {
        Add-C 'MEMORY' 1 "Windows event $($e.Time.ToString('yyyy-MM-dd HH:mm:ss')): $($e.Detail)"
    }
    # Last commands before the crash.
    $last3 = @($s.LastCommands | Select-Object -Last 3)
    $ext = $last3 | Where-Object { $_.External } | Select-Object -Last 1
    if ($ext -and $ext.External -notmatch '^(Autodesk|Revit)') {
        # A command alone is only a hint. It can lead only when there is real crash evidence.
        $conf = if (-not $hasMarker) { 0 } elseif ($s.ExceptionCode -eq '0xe0434352') { 2 } else { 1 }
        Add-C 'ADDIN' $conf "one of the last 3 commands before the end was an $($ext.Text)"
        if (-not $addinName) { $addinName = $ext.External }
    }
    if ($s.ExceptionCode -eq '0xe0434352') { Add-C 'REVIT_CORE' 1 "exception code 0xe0434352 is a .NET error. Revit caught it, so Windows has no faulting module. It can come from Revit or from an add-in." }
    elseif ($s.ExceptionCode) { Add-C 'REVIT_CORE' 1 "exception code $($s.ExceptionCode) in the journal" }
    # File access.
    $stopAt = if ($s.CrashTime) { $s.CrashTime } else { $s.End }
    $sync = @($s.LastCommands | Select-Object -Last 5 | Where-Object { $_.Time -and $stopAt -and ($stopAt - $_.Time).TotalSeconds -le 180 } | Where-Object { $_.Text -match '(?i)SAVE_TO_CENTRAL|SYNCHRONIZE|RELOAD_LATEST|ID_FILE_SAVE|ID_FILE_OPEN|ID_REVIT_FILE_OPEN|ID_APP_OPEN' })
    $fileErr = @($s.Errors | Where-Object { $_ -match '(?i)\\\\[^\\]+\\|access (is )?denied|being used by another process|locked|FaultException' })
    if ($sync.Count -gt 0) {
        $conf = if (-not $hasMarker) { 0 } elseif ($fileErr.Count -gt 0 -and $s.Worksharing.Count -gt 0) { 2 } else { 1 }
        Add-C 'FILE_ACCESS' $conf ("save or sync with the central model shortly before the end: " + ($sync | Select-Object -Last 1).Text + $(if ($s.Worksharing.Count) { "; model type: " + ($s.Worksharing -join ', ') } else { '' }))
    } elseif ($fileErr.Count -gt 0 -and $s.Worksharing.Count -gt 0) {
        Add-C 'FILE_ACCESS' 1 ("file or server error lines in a work-shared session: " + (Redact ($fileErr | Select-Object -Last 1)))
    }
    # Tie order: evidence AT the crash (module, command) before evidence from earlier in the session.
    $order = @{ ADDIN = 5; GRAPHICS = 4; FILE_ACCESS = 3; REVIT_CORE = 2; MEMORY = 1; UNKNOWN = 0 }
    $ranked = @($c | Sort-Object @{ Expression = { $_.Confidence }; Descending = $true }, @{ Expression = { $order[$_.Class] }; Descending = $true })
    $names = @{ 3 = 'HIGH'; 2 = 'MEDIUM'; 1 = 'LOW'; 0 = 'HINT ONLY' }
    $lead = @($ranked | Where-Object { $_.Confidence -ge 1 })
    if ($lead.Count -eq 0 -or $lead[0].Class -eq 'UNKNOWN' -and $lead[0].Confidence -lt 2) {
        $ev = @($ranked | Where-Object { $_.Class -eq 'UNKNOWN' } | ForEach-Object { $_.Evidence })
        $also = @($ranked | Where-Object { $_.Class -ne 'UNKNOWN' } | ForEach-Object { "$($_.Class) ($($names[$_.Confidence])): $($_.Evidence)" })
        return [pscustomobject]@{ Class = 'UNKNOWN'; Confidence = 'LOW'; Evidence = $ev; AlsoPossible = $also; AddinName = $addinName }
    }
    $top = $lead[0]
    $evid = @($ranked | Where-Object { $_.Class -eq $top.Class } | ForEach-Object { $_.Evidence })
    $also = @($ranked | Where-Object { $_.Class -ne $top.Class -and $_.Class -ne 'UNKNOWN' } | ForEach-Object { "$($_.Class) ($($names[$_.Confidence])): $($_.Evidence)" })
    return [pscustomobject]@{ Class = $top.Class; Confidence = $names[$top.Confidence]; Evidence = $evid; AlsoPossible = $also; AddinName = $addinName }
}

$NextSteps = @{
    MEMORY      = @('Close other programs and other Revit models before you work.', 'Audit and compact the model (Open > Audit, then Save As > Options > Compact).', 'Unload links and close views you do not need.', 'Ask IT if the computer can get more RAM.')
    GRAPHICS    = @('Update the graphics driver from the PC maker or IT.', 'In Revit, open Options > Hardware and turn off "Use hardware acceleration" as a test.', 'Restart Revit and try the same action again.')
    ADDIN       = @('Disable the named add-in and try the same action again (remove or rename its .addin file, or use its own on/off switch).', 'If the crash stops, update the add-in or report it to its maker.')
    REVIT_CORE  = @('Install the latest Revit update for your year.', 'Audit the model, then try the same action again.', 'Send the support pack to Autodesk support if it happens again.')
    FILE_ACCESS = @('Copy the model to a local folder (or make a new local copy of the central model) and try again.', 'Check the network or cloud connection before you save or sync.', 'Ask the team if someone else has the central model or the same elements open.')
    UNKNOWN     = @('Note what you were doing when Revit stopped.', 'Install the latest Revit update, and audit the model.', 'Run this check again after the next crash, so there is more evidence.')
}

$Problem = @($Sessions | Where-Object { $_.Status -in 'CRASH', 'ABRUPT_END' })
foreach ($s in $Sessions) {
    if ($s.Status -in 'CRASH', 'ABRUPT_END') { $s['Diagnosis'] = Classify $s } else { $s['Diagnosis'] = $null }
}

# ---------------------------------------------------------------- report
$out = New-Object System.Collections.Generic.List[string]
function O($m) { $out.Add((Redact $m)) }
O "[crash-doctor] Revit crash report, $($Now.ToString('yyyy-MM-dd HH:mm')), last $Days days$(if ($Year) { ", Revit $Year" })"
O ''
O 'SOURCES'
foreach ($src in $Sources) { O ("  [{0}] {1}{2}" -f $src.State, $src.Source, $(if ($src.Detail) { ": $($src.Detail)" } else { '' })) }
O ''
O "SESSIONS ($($Sessions.Count))"
foreach ($s in ($Sessions | Sort-Object { $_.Start })) {
    $st = if ($s.Start) { $s.Start.ToString('yyyy-MM-dd HH:mm') } else { '?' }
    $en = if ($s.End) { $s.End.ToString('yyyy-MM-dd HH:mm') } else { '?' }
    $models = if ($s.Models.Count) { ($s.Models | Select-Object -First 4) -join ', ' } else { 'no model opened' }
    O ("  {0}  Revit {1}  {2} -> {3}  {4,-13} models: {5}" -f $s.Journal, $s.Year, $st, $en, $s.Status, $models)
}
foreach ($s in ($Sessions | Where-Object { $_.Status -eq 'IN_PROGRESS' })) { O "  NOTE $($s.Journal): $($s.StatusNote)" }
O ''
if ($AgentRuns.Count) {
    O 'AGENT RUNS (newest first, run records only)'
    foreach ($a in $AgentRuns) {
        $what = if ($a.Script) { $a.Script } else { $a.Run }
        O ("  {0}  {1}  status={2}{3}" -f $a.Time.ToString('yyyy-MM-dd HH:mm:ss'), $what, $a.Status, $(if ($a.Error) { " error=$($a.Error)" } else { '' }))
    }
    O ''
}
if ($Events.Count) {
    O "WINDOWS EVENTS FOR REVIT ($($Events.Count))"
    foreach ($e in $Events) {
        $m = if ($e.Module) { " module=$($e.Module) $($e.ModuleVersion)" } else { '' }
        $x = if ($e.ExceptionCode) { " code=$($e.ExceptionCode)" } else { '' }
        $ses = if ($e.Session) { "matches $($e.Session)" } else { 'no matching journal session' }
        O ("  {0}  {1} {2}  {3}{4}{5}  {6}  [{7}]" -f $e.Time.ToString('yyyy-MM-dd HH:mm:ss'), $e.Provider, $e.Id, $e.Kind, $m, $x, $e.Detail, $ses)
    }
    O ''
}
if ($JournalDumps.Count -or $OtherDumps.Count -or $CerReports.Count) {
    O 'CRASH DUMP FILES (listed only, not opened, not uploaded)'
    foreach ($d in $JournalDumps) { O ("  {0}  {1} MB  {2}" -f $d.Time.ToString('yyyy-MM-dd HH:mm:ss'), $d.SizeMB, $d.Name) }
    foreach ($d in $OrphanDumps) { O "  NOTE: $($d.Name) has no full journal file (journal.$($d.Number).txt is missing)." }
    foreach ($d in $OtherDumps) { O ("  {0}  {1} MB  {2}" -f $d.Time.ToString('yyyy-MM-dd HH:mm:ss'), $d.SizeMB, $d.Name) }
    $cerShow = @($CerReports | Where-Object { $_.Product -ne 'not Revit' } | Sort-Object Time)
    foreach ($r in $cerShow) { O ("  {0}  Autodesk crash report {1} ({2}{3}){4}" -f $r.Time.ToString('yyyy-MM-dd HH:mm:ss'), $r.Report, $r.Product, $(if ($r.JournalNumber) { ", for journal.$($r.JournalNumber)" } else { '' }), $(if ($r.Session) { ", matches $($r.Session)" } else { '' })) }
    $hidden = $CerReports.Count - $cerShow.Count
    if ($hidden -gt 0) { O "  ($hidden other Autodesk crash report(s) are for other products and are not listed.)" }
    O ''
}

foreach ($s in ($Problem | Sort-Object { $_.Start })) {
    $dg = $s.Diagnosis
    O "== $($s.Journal) (Revit $($s.Year) $($s.Build)) $($s.Status)"
    O "  $($s.StatusNote)"
    if ($s.Models.Count) { O "  Models: $($s.Models -join ', ')" }
    if ($s.Worksharing.Count) { O "  Model type: $($s.Worksharing -join '; ')" }
    $when = if ($s.CrashTime) { $s.CrashTime } else { $s.End }
    if ($when) { O "  Stopped at: $($when.ToString('yyyy-MM-dd HH:mm:ss'))" }
    $lastRun = @($AgentRuns | Where-Object { $s.Start -and $_.Time -ge $s.Start.AddMinutes(-1) -and $when -and $_.Time -le $when.AddMinutes(3) } | Sort-Object Time | Select-Object -Last 1)
    if ($lastRun) {
        $lrWhat = if ($lastRun.Script) { $lastRun.Script } else { $lastRun.Run }
        O ("  Last agent run before the end: {0} {1} (status {2}{3})" -f $lastRun.Time.ToString('yyyy-MM-dd HH:mm:ss'), $lrWhat, $lastRun.Status, $(if ($lastRun.Error) { ", error $($lastRun.Error)" } else { '' }))
    }
    if ($s.Antecedent) { O "  Active tool at the crash: $($s.Antecedent)" }
    if ($s.UndoAfterCrash.Count) { O "  Revit rolled back: $($s.UndoAfterCrash -join '; ')" }
    if ($s.ExceptionCode) { O "  Exception code: $($s.ExceptionCode)" }
    if ($s.LastRam) { O "  Last memory reading: $($s.LastRam.AvailMB) MB of $($s.LastRam.TotalMB) MB RAM free; Revit used $($s.LastRam.RevitInUseMB) MB (peak $($s.LastRam.RevitPeakMB) MB)" }
    O "  Last commands before the end (oldest first):"
    if ($s.LastCommands.Count -eq 0) { O '    (none recorded)' }
    foreach ($c in $s.LastCommands) { O ("    {0}  {1}{2}" -f $(if ($c.Time) { $c.Time.ToString('MM-dd HH:mm:ss') } else { '--:--:--' }), $c.Text, $(if ($c.Count -gt 1) { " (x$($c.Count))" } else { '' })) }
    $errs = @($s.Errors | Select-Object -Last 8)
    if ($errs.Count) { O '  Error lines (last 8, redacted):'; foreach ($x in $errs) { O "    $x" } }
    $third = @(Get-ThirdParty $s | ForEach-Object { $_.Name } | Select-Object -Unique)
    if ($third.Count) { O "  Third-party add-ins: $($third -join ', ')" }
    O "  LIKELY CAUSE: $($dg.Class) (confidence $($dg.Confidence))"
    foreach ($x in $dg.Evidence) { O "    evidence: $x" }
    foreach ($x in $dg.AlsoPossible) { O "    also possible: $x" }
    O '  Next steps (one at a time):'
    $i = 1
    foreach ($x in $NextSteps[$dg.Class]) {
        if ($dg.Class -eq 'ADDIN' -and $dg.AddinName) { $x = $x -replace 'the named add-in', "the add-in '$($dg.AddinName)'" }
        O "    $i. $x"; $i++
    }
    O ''
}

$unreadable = @($Sources | Where-Object { $_.State -eq 'could-not-read' })
$crashes = @($Problem | Where-Object { $_.Status -eq 'CRASH' }).Count
$abrupt  = @($Problem | Where-Object { $_.Status -eq 'ABRUPT_END' }).Count
$evCrash = @($Events | Where-Object { $_.Kind -in 'CRASH', 'HANG', 'DOTNET_ERROR' }).Count
# Journals are the primary source: with no journal read, the session picture is missing (exit 2).
$anyRead = ($JournalsRead -gt 0)
O 'SUMMARY'
if (-not $anyRead) {
    O '  Could not read any Revit journal (none found, none recent, or no access). This is NOT a "no crash" result.'
    if ($EventsRead) { O "  Windows events were read: $evCrash Revit crash/freeze event(s). See the list above." }
    else { O '  The Windows event log could not be read either.' }
    O '  Check the Revit year and the number of days, then run the check again.'
} else {
    O "  $crashes crash(es), $abrupt abrupt end(s), $evCrash Windows crash/freeze event(s) in the last $Days days."
    if ($OrphanDumps.Count) { O "  $($OrphanDumps.Count) more Revit crash dump(s) have no full journal, so those crashes cannot be explained here." }
    if (-not $EventsRead) { O '  Could not read the Windows event log. The result uses journals only.' }
    if ($crashes + $abrupt + $evCrash + $OrphanDumps.Count -eq 0) {
        if ($unreadable.Count) { O "  No crash found in the sources that could be read. $($unreadable.Count) source(s) could not be read, so a crash there is not ruled out." }
        else { O '  No crash found in the sources that could be read.' }
    }
}
O "  Log: $LogFile"
foreach ($l in $out) { Say $l }

# ---------------------------------------------------------------- JSON
if ($Json) {
    try {
        $obj = [ordered]@{
            generated = $Now.ToString('s'); days = $Days; year = $Year
            sources = @($Sources | ForEach-Object { [ordered]@{ source = (Redact $_.Source); state = $_.State; detail = (Redact "$($_.Detail)") } })
            sessions = @($Sessions | ForEach-Object {
                $s = $_
                [ordered]@{
                    journal = $s.Journal; year = $s.Year; build = $s.Build
                    start = if ($s.Start) { $s.Start.ToString('s') } else { $null }; end = if ($s.End) { $s.End.ToString('s') } else { $null }
                    status = $s.Status; note = $s.StatusNote; models = @($s.Models | ForEach-Object { Redact $_ }); modelType = @($s.Worksharing)
                    crashTime = if ($s.CrashTime) { $s.CrashTime.ToString('s') } else { $null }; exceptionCode = $s.ExceptionCode
                    activeTool = (Redact $s.Antecedent); rolledBack = @($s.UndoAfterCrash | ForEach-Object { Redact $_ })
                    lastRam = if ($s.LastRam) { [ordered]@{ availMB = $s.LastRam.AvailMB; totalMB = $s.LastRam.TotalMB; revitInUseMB = $s.LastRam.RevitInUseMB; revitPeakMB = $s.LastRam.RevitPeakMB; time = $(if ($s.LastRam.Time) { $s.LastRam.Time.ToString('s') } else { $null }) } } else { $null }
                    lastCommands = @($s.LastCommands | ForEach-Object { Redact $_.Text })
                    errors = @($s.Errors | Select-Object -Last 15 | ForEach-Object { Redact $_ })
                    dumps = @($s.Dumps | ForEach-Object { $_.Name }); events = @($s.Events | ForEach-Object { "$($_.Time.ToString('s')) $($_.Kind) $($_.Module)".Trim() })
                    diagnosis = if ($s.Diagnosis) { [ordered]@{ class = $s.Diagnosis.Class; confidence = $s.Diagnosis.Confidence; evidence = @($s.Diagnosis.Evidence | ForEach-Object { Redact $_ }); alsoPossible = @($s.Diagnosis.AlsoPossible | ForEach-Object { Redact $_ }) } } else { $null }
                }
            })
            events = @($Events | ForEach-Object { [ordered]@{ time = $_.Time.ToString('s'); provider = $_.Provider; id = $_.Id; kind = $_.Kind; module = (Redact $_.Module); moduleVersion = $_.ModuleVersion; exceptionCode = $_.ExceptionCode; detail = (Redact $_.Detail); session = $_.Session } })
            dumps = @($JournalDumps | ForEach-Object { [ordered]@{ name = $_.Name; time = $_.Time.ToString('s'); sizeMB = $_.SizeMB } })
            otherDumps = @($OtherDumps | ForEach-Object { [ordered]@{ name = $_.Name; time = $_.Time.ToString('s'); sizeMB = $_.SizeMB } })
            cerReports = @($CerReports | ForEach-Object { [ordered]@{ report = $_.Report; time = $_.Time.ToString('s') } })
            agentRuns = @($AgentRuns | ForEach-Object { [ordered]@{ time = $_.Time.ToString('s'); run = $_.Run; status = $_.Status; error = (Redact "$($_.Error)"); script = (Redact "$($_.Script)") } })
        }
        $text = $obj | ConvertTo-Json -Depth 8
        [IO.File]::WriteAllText($Json, $text, (New-Object Text.UTF8Encoding $false))
        Say "[crash-doctor] JSON written: $(Redact $Json)"
    } catch { Say "[crash-doctor] WARNING: could not write JSON: $($_.Exception.Message)" }
}

# ---------------------------------------------------------------- support pack (only when asked)
if ($SupportPack) {
    try {
        $stage = Join-Path $WorkDir 'support-pack'
        New-Item -ItemType Directory -Force $stage | Out-Null
        $enc = New-Object Text.UTF8Encoding $false
        [IO.File]::WriteAllText((Join-Path $stage 'report.txt'), ($out -join "`r`n"), $enc)
        $evText = @($Events | ForEach-Object { Redact ("{0} {1} {2} {3} module={4} {5} code={6} {7} session={8}" -f $_.Time.ToString('s'), $_.Provider, $_.Id, $_.Kind, $_.Module, $_.ModuleVersion, $_.ExceptionCode, $_.Detail, $_.Session) })
        [IO.File]::WriteAllText((Join-Path $stage 'events.txt'), ($evText -join "`r`n"), $enc)
        foreach ($s in $Problem) {
            $jp = ($JournalFiles | Where-Object { (Leaf $_.Path) -eq $s.Journal } | Select-Object -First 1).Path
            if (-not $jp) { continue }
            $center = if ($s.CrashLine) { $s.CrashLine } else { $s.LineCount }
            $from = [Math]::Max(1, $center - 150); $to = $center + 60
            $buf = New-Object System.Collections.Generic.List[string]
            $rd = Open-Lines $jp; $k = 0
            try { while ($null -ne ($line = $rd.ReadLine())) { $k++; if ($k -ge $from -and $k -le $to) { $buf.Add((Redact $line)) }; if ($k -gt $to) { break } } } finally { $rd.Close() }
            [IO.File]::WriteAllText((Join-Path $stage "excerpt-$($s.Journal)"), ("REDACTED excerpt, lines $from-$to`r`n" + ($buf -join "`r`n")), $enc)
        }
        if (-not (Test-Path -LiteralPath $SupportPack)) { New-Item -ItemType Directory -Force $SupportPack | Out-Null }
        $zip = Join-Path $SupportPack "revit-crash-support-$Stamp.zip"
        Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -Force
        Say "[crash-doctor] Support pack written: $(Redact $zip). Nothing was uploaded. Read it before you send it."
    } catch { Say "[crash-doctor] WARNING: could not build the support pack: $($_.Exception.Message)" }
}

if (-not $anyRead) { Done 2 }
Done 0

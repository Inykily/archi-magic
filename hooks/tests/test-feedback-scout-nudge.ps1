<#
.SYNOPSIS
  Tests for hooks/feedback-scout-nudge.ps1. Hermetic: temp state file and log
  folders, a fixed clock (-NowUtc). No network, no real session.

  powershell -NoProfile -ExecutionPolicy Bypass -File hooks\tests\test-feedback-scout-nudge.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Hook = (Resolve-Path (Join-Path $PSScriptRoot '..\feedback-scout-nudge.ps1')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-feedback-scout-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Asserts = 0
$T0 = '2026-11-02T10:00:00.0000000Z'

function Invoke-Hook([string]$state, [string]$now, [string]$hookEvent) {
    # Call the hook the way hooks/hooks.json does: hook JSON on stdin, script called in-process.
    # Passing the JSON as a native argument loses its double quotes under Windows PowerShell 5.1 (#67).
    $json = '{"hook_event_name":"' + $hookEvent + '","session_id":"s1"}'
    $cmd = "`$in = [Console]::In.ReadToEnd(); & '$Hook' -HookInputJson `$in -StateFile '$state' -NowUtc '$now'; exit `$LASTEXITCODE"
    $out = $json | & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $cmd 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out.Trim() }
}
function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name : $detail" }
}
function Write-State([string]$name, [string]$lastNudge) {
    $p = Join-Path $Root $name
    [IO.File]::WriteAllText($p, ('{"last_nudge":"' + $lastNudge + '"}'))
    return $p
}
function Get-Last([string]$p) { ([IO.File]::ReadAllText($p) | ConvertFrom-Json).last_nudge }
function Plus([int]$minutes) { ([datetime]::Parse($T0, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AdjustToUniversal)).AddMinutes($minutes).ToString('o') }

try {
    New-Item -ItemType Directory -Force $Root | Out-Null
    $env:ARCHI_MAGIC_LOG_DIR = Join-Path $Root 'logs'
    $env:ARCHI_MAGIC_NO_FEEDBACK_NUDGE = $null
    $env:ARCHI_MAGIC_SCOUT_INTERVAL_MIN = $null

    # 1. First run: starts the clock, prints nothing.
    $s = Join-Path $Root 'first.json'
    $r = Invoke-Hook $s $T0 'SessionStart'
    Assert-True 'first run: exit 0, no output' ($r.Code -eq 0 -and $r.Out -eq '') "exit $($r.Code) out '$($r.Out)'"
    Assert-True 'first run: state written' ((Test-Path -LiteralPath $s) -and ((Get-Last $s) -like '2026-11-02T10:00:00*')) 'no state'

    # 2. Inside the interval (119 min): quiet, state unchanged.
    $s = Write-State 'inside.json' $T0
    $r = Invoke-Hook $s (Plus 119) 'UserPromptSubmit'
    Assert-True 'inside interval: no output' ($r.Code -eq 0 -and $r.Out -eq '') "out '$($r.Out)'"
    Assert-True 'inside interval: state unchanged' ((Get-Last $s) -eq $T0) (Get-Last $s)

    # 3. Interval passed (120 min): one JSON nudge, state moves to now.
    $r = Invoke-Hook $s (Plus 120) 'UserPromptSubmit'
    $j = $null; try { $j = $r.Out | ConvertFrom-Json } catch { }
    Assert-True 'due: valid JSON' ($null -ne $j) $r.Out
    Assert-True 'due: event is UserPromptSubmit' ($j -and $j.hookSpecificOutput.hookEventName -eq 'UserPromptSubmit') $r.Out
    Assert-True 'due: names the scout agent' ($j -and $j.hookSpecificOutput.additionalContext -match 'archi-magic:am-feedback-scout') $r.Out
    Assert-True 'due: passes since = previous nudge' ($j -and $j.hookSpecificOutput.additionalContext -match 'since=2026-11-02T10:00:00') $r.Out
    Assert-True 'due: never posts itself' ($j -and $j.hookSpecificOutput.additionalContext -match 'Post nothing yourself') $r.Out
    Assert-True 'due: user line says nothing is posted' ($j -and $j.systemMessage -match 'Nothing is posted') $r.Out
    Assert-True 'due: state moved to now' ((Get-Last $s) -like '2026-11-02T12:00:00*') (Get-Last $s)

    # 4. Right after a nudge: quiet again.
    $r = Invoke-Hook $s (Plus 125) 'UserPromptSubmit'
    Assert-True 'after nudge: quiet' ($r.Out -eq '') "out '$($r.Out)'"

    # 5. SessionStart event is echoed back.
    $s = Write-State 'start.json' $T0
    $r = Invoke-Hook $s (Plus 300) 'SessionStart'
    $j = $null; try { $j = $r.Out | ConvertFrom-Json } catch { }
    Assert-True 'session start: event is SessionStart' ($j -and $j.hookSpecificOutput.hookEventName -eq 'SessionStart') $r.Out

    # 6. Other events: quiet, state unchanged.
    $s = Write-State 'other.json' $T0
    $r = Invoke-Hook $s (Plus 300) 'Stop'
    Assert-True 'other event: quiet' ($r.Out -eq '' -and (Get-Last $s) -eq $T0) "out '$($r.Out)'"

    # 7. Interval from the environment (30 min).
    $env:ARCHI_MAGIC_SCOUT_INTERVAL_MIN = '30'
    $s = Write-State 'env30.json' $T0
    $r = Invoke-Hook $s (Plus 45) 'UserPromptSubmit'
    Assert-True 'env interval 30: nudges at 45 min' ($r.Out -match 'am-feedback-scout') "out '$($r.Out)'"

    # 8. Interval 0 turns it off.
    $env:ARCHI_MAGIC_SCOUT_INTERVAL_MIN = '0'
    $s = Write-State 'off.json' $T0
    $r = Invoke-Hook $s (Plus 600) 'UserPromptSubmit'
    Assert-True 'interval 0: off' ($r.Out -eq '' -and (Get-Last $s) -eq $T0) "out '$($r.Out)'"
    $env:ARCHI_MAGIC_SCOUT_INTERVAL_MIN = $null

    # 9. Opt-out of all feedback nudges.
    $env:ARCHI_MAGIC_NO_FEEDBACK_NUDGE = '1'
    $s = Write-State 'optout.json' $T0
    $r = Invoke-Hook $s (Plus 600) 'UserPromptSubmit'
    Assert-True 'opt-out: quiet, state unchanged' ($r.Out -eq '' -and (Get-Last $s) -eq $T0) "out '$($r.Out)'"
    $env:ARCHI_MAGIC_NO_FEEDBACK_NUDGE = $null

    # 10. Unreadable state: start a new interval, no output, exit 0.
    $s = Join-Path $Root 'bad.json'
    [IO.File]::WriteAllText($s, 'not json')
    $r = Invoke-Hook $s (Plus 600) 'UserPromptSubmit'
    Assert-True 'bad state: exit 0, quiet' ($r.Code -eq 0 -and $r.Out -eq '') "exit $($r.Code) out '$($r.Out)'"
    Assert-True 'bad state: rewritten' ((Get-Last $s) -like '2026-11-02T20:00:00*') ([IO.File]::ReadAllText($s))
} finally {
    $env:ARCHI_MAGIC_LOG_DIR = $null
    $env:ARCHI_MAGIC_NO_FEEDBACK_NUDGE = $null
    $env:ARCHI_MAGIC_SCOUT_INTERVAL_MIN = $null
    try { Remove-Item -Recurse -Force $Root } catch { }
}
Write-Host ("{0} asserts, {1} failed" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL no asserts ran'; exit 1 }
exit [int]($script:Fail -gt 0)

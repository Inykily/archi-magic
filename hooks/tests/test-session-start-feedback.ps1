<#
.SYNOPSIS
  Tests for hooks/session-start-feedback.ps1. Hermetic: temp feedback file
  and log folders. No network, no real session.

  powershell -NoProfile -ExecutionPolicy Bypass -File hooks\tests\test-session-start-feedback.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Hook = (Resolve-Path (Join-Path $PSScriptRoot '..\session-start-feedback.ps1')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-session-start-feedback-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Asserts = 0

function Invoke-Hook([string]$feedback) {
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Hook -FeedbackFile $feedback 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out.Trim() }
}
function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name : $detail" }
}
function Write-Note([string]$name, [string]$title, [string]$signals) {
    $p = Join-Path $Root $name
    $note = [ordered]@{
        signals    = @($signals -split ',')
        title      = $title
        body       = "Signals seen: $signals."
        session_id = 's1'
        ended_at   = '2026-10-27T00:00:00Z'
        transcript = 'C:\fake\transcript.jsonl'
    }
    [IO.File]::WriteAllText($p, (New-Object PSObject -Property $note | ConvertTo-Json -Compress -Depth 3))
    return $p
}
function Get-LogText { (Get-ChildItem (Join-Path $Root 'logs') -Filter *.jsonl -ErrorAction SilentlyContinue | Get-Content -Raw) -join '' }

try {
    New-Item -ItemType Directory -Force $Root | Out-Null
    $env:ARCHI_MAGIC_LOG_DIR = Join-Path $Root 'logs'

    # 1. No note file: no output, exit 0.
    $r = Invoke-Hook (Join-Path $Root 'missing.json')
    Assert-True 'no note: exit 0, no output' ($r.Code -eq 0 -and $r.Out -eq '') "exit $($r.Code) out '$($r.Out)'"

    # 2. Valid note: one JSON object, names the problem, consumed once.
    $f = Write-Note 'note.json' 'Revit connection dropped (pipe_error)' 'pipe_error,tool_failed'
    $r = Invoke-Hook $f
    $j = $null; try { $j = $r.Out | ConvertFrom-Json } catch { }
    Assert-True 'note: exit 0' ($r.Code -eq 0) "exit $($r.Code)"
    Assert-True 'note: valid JSON' ($null -ne $j) $r.Out
    Assert-True 'note: systemMessage names the title' ($j -and $j.systemMessage -match 'pipe_error') $r.Out
    Assert-True 'note: systemMessage offers filing' ($j -and $j.systemMessage -match 'GitHub issue') $r.Out
    Assert-True 'note: additionalContext for SessionStart' ($j -and $j.hookSpecificOutput.hookEventName -eq 'SessionStart' -and $j.hookSpecificOutput.additionalContext -match 'gh issue create') $r.Out
    Assert-True 'note: additionalContext says file only on yes' ($j -and $j.hookSpecificOutput.additionalContext -match 'only if the user says yes') $r.Out
    Assert-True 'note: file consumed' (-not (Test-Path -LiteralPath $f)) 'note still there'

    # 3. Second run: nothing left to show.
    $r = Invoke-Hook $f
    Assert-True 'consumed: second run quiet' ($r.Code -eq 0 -and $r.Out -eq '') "out '$($r.Out)'"

    # 4. Corrupt note: no output, exit 0, file deleted (no repeat nag).
    $f = Join-Path $Root 'corrupt.json'
    [IO.File]::WriteAllText($f, '{not json')
    $r = Invoke-Hook $f
    Assert-True 'corrupt: exit 0, no output' ($r.Code -eq 0 -and $r.Out -eq '') "exit $($r.Code) out '$($r.Out)'"
    Assert-True 'corrupt: file deleted' (-not (Test-Path -LiteralPath $f)) 'corrupt file still there'

    # 5. Opt-out: no output, file deleted.
    $env:ARCHI_MAGIC_NO_FEEDBACK_NUDGE = '1'
    $f = Write-Note 'optout.json' 'A tool call failed' 'tool_failed'
    $r = Invoke-Hook $f
    Remove-Item Env:\ARCHI_MAGIC_NO_FEEDBACK_NUDGE
    Assert-True 'opt-out: no output' ($r.Out -eq '') "out '$($r.Out)'"
    Assert-True 'opt-out: file deleted' (-not (Test-Path -LiteralPath $f)) 'note still there'

    # 6. Showing a note is logged.
    Assert-True 'note shown: logged' ((Get-LogText) -match '"step":"session-start-feedback","level":"info"') (Get-LogText)
} finally {
    Remove-Item Env:\ARCHI_MAGIC_LOG_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:\ARCHI_MAGIC_NO_FEEDBACK_NUDGE -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Root
}

Write-Host ("{0} assertion(s), {1} failure(s)" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL: no assertions ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

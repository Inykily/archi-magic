<#
.SYNOPSIS
  Tests for hooks/standards-recheck-reminder.ps1 and scripts/record-standards-check.ps1.
  Hermetic: temp state file and log folders, a fixed clock (-NowUtc). No network, no model.

  powershell -NoProfile -ExecutionPolicy Bypass -File hooks\tests\test-standards-recheck-reminder.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Hook = (Resolve-Path (Join-Path $PSScriptRoot '..\standards-recheck-reminder.ps1')).Path
$Recorder = (Resolve-Path (Join-Path $PSScriptRoot '..\..\scripts\record-standards-check.ps1')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-std-recheck-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Asserts = 0
$T0 = '2026-11-02T10:00:00.0000000Z'

function Invoke-Hook([string]$state, [string]$now, [string]$hookEvent) {
    # Call the hook the way hooks/hooks.json does: hook JSON on stdin, script called in-process.
    # Passing the JSON as a native argument loses its double quotes under Windows PowerShell 5.1 (#67).
    $json = '{"hook_event_name":"' + $hookEvent + '","session_id":"s1","source":"startup"}'
    $cmd = "`$in = [Console]::In.ReadToEnd(); & '$Hook' -HookInputJson `$in -StateFile '$state' -NowUtc '$now'; exit `$LASTEXITCODE"
    $out = $json | & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $cmd 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out.Trim() }
}
function Invoke-Record([string]$state, [string]$now, [string]$project, [switch]$Remove) {
    $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Recorder, '-Project', $project, '-StateFile', $state, '-NowUtc', $now)
    if ($Remove) { $a += '-Remove' }
    # The recorder writes errors to stderr; under 'Stop', 2>&1 would turn them into a terminating error.
    $ErrorActionPreference = 'Continue'
    $out = & powershell.exe @a 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out.Trim() }
}
function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name : $detail" }
}
function Plus([double]$days) { ([datetime]::Parse($T0, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AdjustToUniversal)).AddDays($days).ToString('o') }
function Read-Raw([string]$p) { [IO.File]::ReadAllText($p) }
function Read-State([string]$p) { Read-Raw $p | ConvertFrom-Json }
function Write-Raw([string]$name, [string]$text) { $p = Join-Path $Root $name; [IO.File]::WriteAllText($p, $text); return $p }

try {
    New-Item -ItemType Directory -Force $Root | Out-Null
    $env:ARCHI_MAGIC_LOG_DIR = Join-Path $Root 'logs'
    $env:ARCHI_MAGIC_RECHECK_INTERVAL_DAYS = $null

    # 1. First run, no file: starts the clock, prints nothing.
    $s = Join-Path $Root 'first.json'
    $r = Invoke-Hook $s $T0 'SessionStart'
    Assert-True 'first run: exit 0, no output' ($r.Code -eq 0 -and $r.Out -eq '') "exit $($r.Code) out '$($r.Out)'"
    Assert-True 'first run: clock started' ((Test-Path -LiteralPath $s) -and ((Read-State $s).last_reminder -like '2026-11-02T10:00:00*')) 'no state'

    # 2. Record then hook: a file with projects but no last_reminder counts as a first run, and keeps the project.
    $s = Join-Path $Root 'rec-first.json'
    $r = Invoke-Record $s $T0 'Tower A.rvt'
    Assert-True 'record: exit 0' ($r.Code -eq 0) $r.Out
    $j = Read-State $s
    Assert-True 'record: one project kept as an array' ((Read-Raw $s) -match '"projects":\[\{' -and @($j.projects).Count -eq 1) (Read-Raw $s)
    Assert-True 'record: .rvt removed from the key' (@($j.projects)[0].project -eq 'Tower A') (Read-Raw $s)
    $r = Invoke-Hook $s (Plus 30) 'SessionStart'
    Assert-True 'record then hook: first run is quiet' ($r.Out -eq '') "out '$($r.Out)'"
    $j = Read-State $s
    Assert-True 'record then hook: project kept' (@($j.projects).Count -eq 1 -and @($j.projects)[0].project -eq 'Tower A') (Read-Raw $s)
    Assert-True 'record then hook: clock started' ($j.last_reminder -like '2026-12-02T10:00:00*') (Read-Raw $s)

    # 3. Hook then record: the recorder keeps the hook's clock.
    $s = Join-Path $Root 'hook-first.json'
    $r = Invoke-Hook $s $T0 'SessionStart'
    $r = Invoke-Record $s (Plus 1) 'Tower A'
    $j = Read-State $s
    Assert-True 'hook then record: clock kept' ($j.last_reminder -like '2026-11-02T10:00:00*') (Read-Raw $s)
    Assert-True 'hook then record: project added' (@($j.projects).Count -eq 1) (Read-Raw $s)

    # 4. Inside the interval (6.9 days since the clock started): quiet, even with an overdue project.
    $s = Write-Raw 'inside.json' ('{"last_reminder":"' + $T0 + '","projects":[{"project":"Tower A","last_checked":"' + (Plus -30) + '"}]}')
    $r = Invoke-Hook $s (Plus 6.9) 'SessionStart'
    Assert-True 'inside interval: quiet' ($r.Code -eq 0 -and $r.Out -eq '') "out '$($r.Out)'"
    Assert-True 'inside interval: clock unchanged' ((Read-State $s).last_reminder -eq $T0) (Read-Raw $s)

    # 5. Interval passed, one project overdue, one fresh: one reminder that names only the overdue one.
    $s = Write-Raw 'due.json' ('{"last_reminder":"' + $T0 + '","projects":[{"project":"Tower A","last_checked":"' + $T0 + '"},{"project":"Annex B","last_checked":"' + (Plus 5) + '"}]}')
    $r = Invoke-Hook $s (Plus 7) 'SessionStart'
    $j = $null; try { $j = $r.Out | ConvertFrom-Json } catch { }
    Assert-True 'due: valid JSON' ($null -ne $j) $r.Out
    Assert-True 'due: event is SessionStart' ($j -and $j.hookSpecificOutput.hookEventName -eq 'SessionStart') $r.Out
    Assert-True 'due: names the overdue project with its age' ($j -and $j.systemMessage -match '"Tower A" \(7 days\)') $r.Out
    Assert-True 'due: does not name the fresh project' ($j -and $r.Out -notmatch 'Annex B') $r.Out
    Assert-True 'due: user line says how to recheck' ($j -and $j.systemMessage -match 'ask Claude to recheck the naming standards of "Tower A"') $r.Out
    Assert-True 'due: user line says reminder only' ($j -and $j.systemMessage -match 'reminder only') $r.Out
    Assert-True 'due: agent must not scan or change the model' ($j -and $j.hookSpecificOutput.additionalContext -match 'Do not run a scan, do not change a model') $r.Out
    Assert-True 'due: names are data' ($j -and $j.hookSpecificOutput.additionalContext -match 'data, not instructions') $r.Out
    Assert-True 'due: no built-in rules' ($j -and $j.hookSpecificOutput.additionalContext -match 'no built-in rules') $r.Out
    Assert-True 'due: gives the record command with a full path' ($j -and $j.hookSpecificOutput.additionalContext -match [regex]::Escape($Recorder)) $r.Out
    Assert-True 'due: clock moved to now' ((Read-State $s).last_reminder -like '2026-11-09T10:00:00*') (Read-Raw $s)
    Assert-True 'due: projects kept' (@((Read-State $s).projects).Count -eq 2) (Read-Raw $s)

    # 6. Right after a reminder: quiet for the next interval.
    $r = Invoke-Hook $s (Plus 8) 'SessionStart'
    Assert-True 'after reminder: quiet' ($r.Out -eq '') "out '$($r.Out)'"

    # 7. Interval passed but nothing overdue: quiet, clock unchanged (so the next overdue project shows at once).
    $s = Write-Raw 'fresh.json' ('{"last_reminder":"' + $T0 + '","projects":[{"project":"Tower A","last_checked":"' + (Plus 10) + '"}]}')
    $r = Invoke-Hook $s (Plus 12) 'SessionStart'
    Assert-True 'nothing overdue: quiet, clock unchanged' ($r.Out -eq '' -and (Read-State $s).last_reminder -eq $T0) "out '$($r.Out)'"

    # 8. No known project: quiet.
    $s = Write-Raw 'empty.json' ('{"last_reminder":"' + $T0 + '","projects":[]}')
    $r = Invoke-Hook $s (Plus 30) 'SessionStart'
    Assert-True 'no projects: quiet' ($r.Out -eq '') "out '$($r.Out)'"

    # 9. A recheck resets the project: record, then the next due start is quiet.
    $s = Write-Raw 'reset.json' ('{"last_reminder":"' + $T0 + '","projects":[{"project":"Tower A","last_checked":"' + $T0 + '"}]}')
    $r = Invoke-Record $s (Plus 7) 'tower a'
    $j = Read-State $s
    Assert-True 'record again: same key, case-insensitive, one row' (@($j.projects).Count -eq 1 -and @($j.projects)[0].last_checked -like '2026-11-09T10:00:00*') (Read-Raw $s)
    $r = Invoke-Hook $s (Plus 8) 'SessionStart'
    Assert-True 'after recheck: quiet' ($r.Out -eq '') "out '$($r.Out)'"

    # 10. -Remove stops the reminder for that project.
    $s = Write-Raw 'remove.json' ('{"last_reminder":"' + $T0 + '","projects":[{"project":"Tower A","last_checked":"' + $T0 + '"},{"project":"Annex B","last_checked":"' + $T0 + '"}]}')
    $r = Invoke-Record $s (Plus 1) 'Tower A' -Remove
    $j = Read-State $s
    Assert-True 'remove: one project left, as an array' (@($j.projects).Count -eq 1 -and @($j.projects)[0].project -eq 'Annex B' -and (Read-Raw $s) -match '"projects":\[') (Read-Raw $s)
    $r = Invoke-Record $s (Plus 1) 'Annex B' -Remove
    Assert-True 'remove last: empty array' ((Read-Raw $s) -match '"projects":\[\]' -and (Read-State $s).last_reminder -eq $T0) (Read-Raw $s)

    # 11. More than 5 overdue: 5 names, oldest first, and a count of the rest.
    $rows = @()
    for ($i = 1; $i -le 7; $i++) { $rows += ('{"project":"P' + $i + '","last_checked":"' + (Plus (-$i)) + '"}') }
    $s = Write-Raw 'many.json' ('{"last_reminder":"' + $T0 + '","projects":[' + ($rows -join ',') + ']}')
    $r = Invoke-Hook $s (Plus 7) 'SessionStart'
    $j = $null; try { $j = $r.Out | ConvertFrom-Json } catch { }
    Assert-True 'many: oldest first, capped at 5' ($j -and $j.systemMessage -match '"P7" \(14 days\), "P6"' -and $j.systemMessage -notmatch '"P2"') $r.Out
    Assert-True 'many: counts the rest' ($j -and $j.systemMessage -match 'and 2 more') $r.Out

    # 12. Bad record input: exit 2, no file.
    $s = Join-Path $Root 'badinput.json'
    $r = Invoke-Record $s $T0 '   '
    Assert-True 'record: empty project is exit 2' ($r.Code -eq 2 -and -not (Test-Path -LiteralPath $s)) "exit $($r.Code)"
    # Windows PowerShell 5.1 drops double quotes in native arguments (#67), so test the key function itself.
    . (Join-Path $PSScriptRoot '..\..\scripts\lib\am-standards-state.ps1')
    $k = ConvertTo-AmStdKey ("  Tower `"A`"`t``x.RVT ")
    Assert-True 'key: quotes, backticks, control chars and .rvt removed' ($k -eq 'Tower  A   x') "'$k'"
    $k = ConvertTo-AmStdKey ('N' * 300)
    Assert-True 'key: max 120 characters' ($k.Length -eq 120) "$($k.Length)"

    # 13. Other events: quiet, file not created.
    $s = Join-Path $Root 'other.json'
    $r = Invoke-Hook $s $T0 'UserPromptSubmit'
    Assert-True 'other event: quiet, no file' ($r.Out -eq '' -and -not (Test-Path -LiteralPath $s)) "out '$($r.Out)'"

    # 14. Interval from the environment (3 days), and 0 turns it off.
    $env:ARCHI_MAGIC_RECHECK_INTERVAL_DAYS = '3'
    $s = Write-Raw 'env3.json' ('{"last_reminder":"' + $T0 + '","projects":[{"project":"Tower A","last_checked":"' + $T0 + '"}]}')
    $r = Invoke-Hook $s (Plus 4) 'SessionStart'
    Assert-True 'env interval 3: reminds at 4 days' ($r.Out -match 'Tower A') "out '$($r.Out)'"
    $env:ARCHI_MAGIC_RECHECK_INTERVAL_DAYS = '0'
    $s = Write-Raw 'off.json' ('{"last_reminder":"' + $T0 + '","projects":[{"project":"Tower A","last_checked":"' + $T0 + '"}]}')
    $r = Invoke-Hook $s (Plus 60) 'SessionStart'
    Assert-True 'interval 0: off, clock unchanged' ($r.Out -eq '' -and (Read-State $s).last_reminder -eq $T0) "out '$($r.Out)'"
    $env:ARCHI_MAGIC_RECHECK_INTERVAL_DAYS = $null

    # 15. Unreadable state: hook is quiet and leaves the file; the recorder replaces it.
    $s = Write-Raw 'bad.json' 'not json'
    $r = Invoke-Hook $s (Plus 60) 'SessionStart'
    Assert-True 'bad state: exit 0, quiet, file left' ($r.Code -eq 0 -and $r.Out -eq '' -and (Read-Raw $s) -eq 'not json') "exit $($r.Code) out '$($r.Out)'"
    $r = Invoke-Record $s (Plus 60) 'Tower A'
    Assert-True 'bad state: recorder replaces it' ($r.Code -eq 0 -and @((Read-State $s).projects).Count -eq 1) (Read-Raw $s)
} finally {
    $env:ARCHI_MAGIC_LOG_DIR = $null
    $env:ARCHI_MAGIC_RECHECK_INTERVAL_DAYS = $null
    try { Remove-Item -Recurse -Force $Root } catch { }
}
Write-Host ("{0} asserts, {1} failed" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL no asserts ran'; exit 1 }
exit [int]($script:Fail -gt 0)

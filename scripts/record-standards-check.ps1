<#
.SYNOPSIS
  Record that the standards of one project were rechecked now (for the soft reminder).

.DESCRIPTION
  Run this after any standards recheck of a model: a naming check, a parameter check, or any
  scan against the project's own rules. It writes "last checked = now" for the project to
  %LOCALAPPDATA%\archi-magic\standards-checks.json. hooks/standards-recheck-reminder.ps1 then
  reminds at session start, once per interval, which projects were not rechecked for N days.

  -Project is the central model name (Revit Document.Title of the central model, without
  ".rvt"). Use the same name each time. Names compare case-insensitively.
  -Remove stops the reminder for that project (for example, the project is finished).

  The script records only. It never runs a scan and never touches a model. No network.
  Exit 0 = recorded. Exit 2 = bad input. Exit 1 = the state file could not be written.

  Test parameters: -StateFile, -NowUtc (ISO 8601).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\record-standards-check.ps1 -Project "Tower A"
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\record-standards-check.ps1 -Project "Tower A" -Remove
#>
param(
    [string]$Project = '',
    [switch]$Remove,
    [string]$StateFile = '',
    [string]$NowUtc = ''
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib\am-standards-state.ps1')

$key = ConvertTo-AmStdKey $Project
if (-not $key) {
    [Console]::Error.WriteLine('record-standards-check: give -Project "<central model name>".')
    exit 2
}
if (-not $StateFile) { $StateFile = Get-AmStdStatePath }
if (-not $StateFile) {
    [Console]::Error.WriteLine('record-standards-check: no LOCALAPPDATA folder.')
    exit 1
}

$now = (Get-Date).ToUniversalTime()
if ($NowUtc) { $now = ConvertFrom-AmStdTime $NowUtc }

try {
    try {
        $state = Read-AmStdState $StateFile
    } catch {
        # An unreadable file has nothing worth keeping. Start again with this project.
        [Console]::Error.WriteLine('record-standards-check: state file unreadable; starting a new one.')
        $state = @{ LastReminder = $null; Projects = New-Object System.Collections.ArrayList }
    }
    $kept = New-Object System.Collections.ArrayList
    foreach ($p in $state.Projects) {
        if (-not [string]::Equals($p.project, $key, [StringComparison]::OrdinalIgnoreCase)) { [void]$kept.Add($p) }
    }
    if (-not $Remove) { [void]$kept.Add(@{ project = $key; last_checked = $now }) }
    $state.Projects = $kept
    Write-AmStdState $StateFile $state
} catch {
    [Console]::Error.WriteLine('record-standards-check: could not write the state file: ' + $_.Exception.Message)
    exit 1
}

if ($Remove) { Write-Host "Removed '$key' from the standards recheck reminder." }
else { Write-Host ("Recorded a standards recheck of '{0}' at {1} UTC." -f $key, $now.ToString('yyyy-MM-dd HH:mm')) }
exit 0

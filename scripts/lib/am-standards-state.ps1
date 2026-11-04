<#
.SYNOPSIS
  Shared state for the standards recheck reminder. Dot-source this file.

.DESCRIPTION
  One small JSON file, %LOCALAPPDATA%\archi-magic\standards-checks.json:
    { "last_reminder": "<ISO 8601 UTC or empty>",
      "projects": [ { "project": "<central model name>", "last_checked": "<ISO 8601 UTC>" } ] }

  scripts/record-standards-check.ps1 writes "projects". hooks/standards-recheck-reminder.ps1
  writes "last_reminder". Each writer keeps the other writer's field.

  A project key is the central model name: trimmed, control characters, double quotes and
  backticks removed, a trailing
  ".rvt" removed, a trailing "_<user name>" of a local copy is NOT removed (we cannot tell it
  from a real name part), max 120 characters. Keys compare case-insensitively.

  Dot-sourcing runs in the caller's scope: every name here starts with AmStd.
#>

function Get-AmStdStatePath {
    $base = $env:LOCALAPPDATA
    if (-not $base) { $base = Join-Path $env:USERPROFILE 'AppData\Local' }
    if (-not $base) { return '' }
    return (Join-Path $base 'archi-magic\standards-checks.json')
}

function ConvertTo-AmStdKey([string]$Name) {
    if ($null -eq $Name) { return '' }
    # Control characters, double quotes and backticks would break the command line in the reminder.
    $k = [regex]::Replace($Name, '[\x00-\x1F\x7F"`]', ' ').Trim()
    $k = [regex]::Replace($k, '\.rvt$', '', 'IgnoreCase').Trim()
    if ($k.Length -gt 120) { $k = $k.Substring(0, 120).Trim() }
    return $k
}

function ConvertFrom-AmStdTime([string]$Text) {
    return [datetime]::Parse($Text, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AdjustToUniversal)
}

# Returns @{ LastReminder = <datetime or $null>; Projects = <ArrayList of @{ project; last_checked }> }.
# A missing file gives an empty state. An unreadable file throws: the caller decides.
function Read-AmStdState([string]$Path) {
    $state = @{ LastReminder = $null; Projects = New-Object System.Collections.ArrayList }
    if (-not (Test-Path -LiteralPath $Path)) { return $state }
    $obj = [IO.File]::ReadAllText($Path) | ConvertFrom-Json
    if ($null -eq $obj) { throw 'empty state file' }
    if ($obj.last_reminder) { $state.LastReminder = ConvertFrom-AmStdTime ([string]$obj.last_reminder) }
    foreach ($p in @($obj.projects)) {
        if ($null -eq $p) { continue }
        $key = ConvertTo-AmStdKey ([string]$p.project)
        if (-not $key -or -not $p.last_checked) { continue }
        try { $when = ConvertFrom-AmStdTime ([string]$p.last_checked) } catch { continue }
        [void]$state.Projects.Add(@{ project = $key; last_checked = $when })
    }
    return $state
}

function Write-AmStdState([string]$Path, $State) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $rows = @()
    foreach ($p in $State.Projects) {
        $rows += New-Object PSObject -Property ([ordered]@{ project = $p.project; last_checked = $p.last_checked.ToString('o') })
    }
    $last = ''
    if ($State.LastReminder) { $last = $State.LastReminder.ToString('o') }
    # -InputObject keeps a one-row list as a JSON array under Windows PowerShell 5.1.
    $projectsJson = ConvertTo-Json -InputObject @($rows) -Depth 4 -Compress
    if ($rows.Count -eq 0) { $projectsJson = '[]' }
    $json = '{"last_reminder":' + (ConvertTo-Json -InputObject $last -Compress) + ',"projects":' + $projectsJson + '}'
    [IO.File]::WriteAllText($Path, $json)
}

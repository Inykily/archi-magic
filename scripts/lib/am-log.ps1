<#
.SYNOPSIS
  Shared local log for archi-magic skill scripts. Dot-source this file, then call Write-AmLog.

.DESCRIPTION
  Each call appends one JSON line to %LOCALAPPDATA%\archi-magic\logs\<yyyy-MM>.jsonl
  (override the folder with $env:ARCHI_MAGIC_LOG_DIR, for tests). Keeps the 6 newest
  monthly files and deletes older ones.

  Fields: ts (UTC ISO 8601), skill, step, level, message, exitCode, archiMagicVersion,
  pyrevitVersion, data. Paths in message and data are rewritten to %APPDATA% / %LOCALAPPDATA% /
  %TEMP% / %USERPROFILE% form. Data values must be scalars; others are dropped.
  Never log model data, file contents, tokens or user names.

  Write-AmLog never throws. A logging failure gives one Write-Warning and nothing else,
  so a caller's behavior and exit code never change because of logging.

  Dot-sourcing runs in the caller's scope: every name here starts with AmLog / Am.

.EXAMPLE
  . "$PSScriptRoot\..\..\..\scripts\lib\am-log.ps1"
  Write-AmLog -Skill am-pyrevit7-setup -Step install -Level error -Message 'Installer failed' -ExitCode 3
#>

$AmLogHelperDir = $PSScriptRoot

function Get-AmLogDir {
    if ($env:ARCHI_MAGIC_LOG_DIR) { return $env:ARCHI_MAGIC_LOG_DIR }
    $base = $env:LOCALAPPDATA
    if (-not $base) { $base = Join-Path $env:USERPROFILE 'AppData\Local' }
    return (Join-Path $base 'archi-magic\logs')
}

function Get-AmPluginVersion {
    if ($script:AmLogPluginVersion) { return $script:AmLogPluginVersion }
    $v = 'unknown'
    try {
        if ($AmLogHelperDir) {
            $pj = Join-Path $AmLogHelperDir '..\..\.claude-plugin\plugin.json'
            if (Test-Path -LiteralPath $pj) {
                $m = [regex]::Match([IO.File]::ReadAllText($pj), '"version"\s*:\s*"([^"]+)"')
                if ($m.Success) { $v = $m.Groups[1].Value }
            }
            if ($v -eq 'unknown') {
                # archi-magic has no pinned version: Claude Code derives it from the commit and installs
                # the plugin under ...\plugins\cache\<marketplace>\archi-magic\<version>\. Use that folder name.
                $pluginRoot = [IO.Path]::GetFullPath((Join-Path $AmLogHelperDir '..\..'))
                $parent = Split-Path -Leaf (Split-Path -Parent $pluginRoot)
                if ($parent -eq 'archi-magic') { $v = Split-Path -Leaf $pluginRoot }
                else { $v = 'source-checkout' }
            }
        }
    } catch { $v = 'unknown' }
    $script:AmLogPluginVersion = $v
    return $v
}

function Get-AmPyRevitVersion {
    # File version only. 'pyrevit --version' goes to the network, so do not call it here.
    if ($script:AmLogPyRevitVersion) { return $script:AmLogPyRevitVersion }
    $v = $null
    try {
        $exe = Join-Path $env:APPDATA 'pyRevit-Master\bin\pyrevit.exe'
        if (Test-Path -LiteralPath $exe) {
            $v = [string](Get-Item -LiteralPath $exe).VersionInfo.FileVersion
            if (-not $v) { $v = 'present' }
        }
    } catch { $v = $null }
    $script:AmLogPyRevitVersion = $v
    return $v
}

function ConvertTo-AmRedacted([string]$Text) {
    # Rewrite user-specific paths to environment-variable form. Longest first: TEMP is under LOCALAPPDATA.
    if (-not $Text) { return $Text }
    $pairs = New-Object System.Collections.Generic.List[object]
    foreach ($name in 'TEMP', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE') {
        $val = [Environment]::GetEnvironmentVariable($name)
        if (-not $val) { continue }
        $forms = @($val.TrimEnd('\'))
        try {
            if (Test-Path -LiteralPath $val) { $forms += (Get-Item -LiteralPath $val).FullName.TrimEnd('\') }
        } catch { }
        foreach ($f in ($forms | Select-Object -Unique)) { $pairs.Add(@($f, "%$name%")) }
    }
    $out = $Text
    foreach ($p in ($pairs | Sort-Object { $_[0].Length } -Descending)) {
        $out = [regex]::Replace($out, [regex]::Escape($p[0]), $p[1], 'IgnoreCase')
        $out = [regex]::Replace($out, [regex]::Escape($p[0].Replace('\', '\\')), $p[1], 'IgnoreCase')
    }
    if ($env:USERNAME -and $env:USERNAME.Length -ge 3) {
        $out = [regex]::Replace($out, '\\Users\\' + [regex]::Escape($env:USERNAME) + '\b', '\Users\<user>', 'IgnoreCase')
    }
    return $out
}

function Write-AmLog {
    [CmdletBinding()]
    param(
        [string]$Skill = 'unknown',
        [string]$Step = '',
        [ValidateSet('info', 'warn', 'error')][string]$Level = 'info',
        [string]$Message = '',
        [Nullable[int]]$ExitCode = $null,
        [hashtable]$Data = $null
    )
    try {
        $dir = Get-AmLogDir
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir -ErrorAction Stop | Out-Null }

        $msg = ConvertTo-AmRedacted $Message
        if ($msg.Length -gt 1000) { $msg = $msg.Substring(0, 1000) + '...' }
        $clean = [ordered]@{}
        if ($Data) {
            foreach ($k in $Data.Keys) {
                $v = $Data[$k]
                if ($null -eq $v) { $clean[[string]$k] = $null; continue }
                if ($v -is [bool] -or $v -is [int] -or $v -is [long] -or $v -is [double]) { $clean[[string]$k] = $v; continue }
                if ($v -is [string] -or $v -is [version] -or $v -is [enum]) {
                    $s = ConvertTo-AmRedacted ([string]$v)
                    if ($s.Length -gt 300) { $s = $s.Substring(0, 300) + '...' }
                    $clean[[string]$k] = $s
                }
            }
        }
        $rec = [ordered]@{
            ts                = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
            skill             = $Skill
            step              = $Step
            level             = $Level
            message           = $msg
            exitCode          = $ExitCode
            archiMagicVersion = (Get-AmPluginVersion)
            pyrevitVersion    = (Get-AmPyRevitVersion)
            data              = $clean
        }
        $line = (New-Object PSObject -Property $rec | ConvertTo-Json -Compress -Depth 3)
        $file = Join-Path $dir ((Get-Date).ToUniversalTime().ToString('yyyy-MM') + '.jsonl')
        [IO.File]::AppendAllText($file, $line + "`n", (New-Object Text.UTF8Encoding $false))

        # Rotate: keep the 6 newest monthly files.
        $old = @(Get-ChildItem -LiteralPath $dir -Filter '*.jsonl' -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^\d{4}-\d{2}\.jsonl$' } | Sort-Object Name -Descending | Select-Object -Skip 6)
        foreach ($o in $old) { Remove-Item -LiteralPath $o.FullName -Force -ErrorAction SilentlyContinue }
    } catch {
        try { Write-Warning "archi-magic log not written: $($_.Exception.Message)" } catch { }
    }
}

<#
.SYNOPSIS
  Bump the archi-magic plugin version in .claude-plugin/plugin.json (semver).
  Installed copies only pick up new content when this version changes.

.EXAMPLE
  powershell -File scripts/bump-version.ps1 patch    # 0.2.0 -> 0.2.1  (fixes, wording)
  powershell -File scripts/bump-version.ps1 minor    # 0.2.0 -> 0.3.0  (new skill, new dependency)
  powershell -File scripts/bump-version.ps1 major    # 0.2.0 -> 1.0.0  (breaking change)
#>
param([Parameter(Mandatory = $true)][ValidateSet('patch', 'minor', 'major')][string]$Part)
$ErrorActionPreference = 'Stop'
$path = Join-Path (Split-Path -Parent $PSScriptRoot) '.claude-plugin/plugin.json'
$text = [IO.File]::ReadAllText($path)
$m = [regex]::Match($text, '"version"\s*:\s*"(\d+)\.(\d+)\.(\d+)"')
if (-not $m.Success) { Write-Host "FAIL: no semver \"version\" in $path"; exit 1 }
$maj = [int]$m.Groups[1].Value; $min = [int]$m.Groups[2].Value; $pat = [int]$m.Groups[3].Value
switch ($Part) {
    'major' { $maj++; $min = 0; $pat = 0 }
    'minor' { $min++; $pat = 0 }
    'patch' { $pat++ }
}
$old = "$($m.Groups[1].Value).$($m.Groups[2].Value).$($m.Groups[3].Value)"
$new = "$maj.$min.$pat"
# Replace only the version value, so the rest of the file keeps its exact formatting.
$text = $text.Substring(0, $m.Index) + ('"version": "' + $new + '"') + $text.Substring($m.Index + $m.Length)
[IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false))
Write-Host "archi-magic version $old -> $new"

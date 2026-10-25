<#
.SYNOPSIS
  Write every shared-file copy listed in scripts/lib/shared-files.ps1 from its source, byte for byte.
  check-skills.ps1 fails when a copy drifts. Run scripts/sync-design-tokens.ps1 first.

.EXAMPLE
  powershell -File scripts/sync-shared-files.ps1
#>
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
. (Join-Path $Root 'scripts/lib/shared-files.ps1')   # defines $AmSharedFiles
if (@($AmSharedFiles).Count -eq 0) { Write-Host 'FAIL: scripts/lib/shared-files.ps1 lists no files'; exit 1 }
$bad = 0
foreach ($f in $AmSharedFiles) {
    $src = Join-Path $Root $f.Source
    $dst = Join-Path $Root $f.Copy
    if (-not (Test-Path -LiteralPath $src)) { Write-Host "MISSING SOURCE $($f.Source)"; $bad++; continue }
    $dir = Split-Path -Parent $dst
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $srcBytes = [IO.File]::ReadAllBytes($src)
    $same = (Test-Path -LiteralPath $dst) -and ([Convert]::ToBase64String([IO.File]::ReadAllBytes($dst)) -eq [Convert]::ToBase64String($srcBytes))
    if ($same) { Write-Host "unchanged $($f.Copy)" }
    else { [IO.File]::WriteAllBytes($dst, $srcBytes); Write-Host "updated   $($f.Copy)" }
}
if ($bad) { exit 1 }
exit 0

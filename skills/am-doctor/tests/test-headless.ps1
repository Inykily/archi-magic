<#
.SYNOPSIS
  Tests for the am-doctor HEADLESS_OLD_PYREVIT check. Hermetic: temp machine and per-user Addins
  folders and a temp "old install". Never touches the real manifests, never runs pyrevit.

  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-doctor\tests\test-headless.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Doctor = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\doctor.ps1')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-doctor-headless-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Asserts = 0

function New-Loader([string]$installRoot, [string]$flavor) {
    $dll = Join-Path $installRoot "bin\$flavor\engines\IPY2712PR\pyRevitLoader.dll"
    New-Item -ItemType Directory -Force (Split-Path -Parent $dll) | Out-Null
    [IO.File]::WriteAllText($dll, 'stub')
    return $dll
}
function New-Manifest([string]$addinsRoot, [string]$year, [string]$assembly) {
    $dir = Join-Path $addinsRoot $year
    New-Item -ItemType Directory -Force $dir | Out-Null
    $xml = "<?xml version=`"1.0`" encoding=`"utf-8`"?><RevitAddIns><AddIn Type=`"Application`"><Name>PyRevitLoader</Name><Assembly>$assembly</Assembly></AddIn></RevitAddIns>"
    [IO.File]::WriteAllText((Join-Path $dir 'pyRevit.addin'), $xml)
}
function Invoke-Doctor([string]$machine, [string]$user, [string]$py7) {
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Doctor -Only repoint -AddinsRoot $machine -UserAddinsRoot $user -Py7Root $py7 -LogDir (Join-Path $Root 'logs') 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out }
}
function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name :`n$detail" }
}
function Get-HeadlessLines([string]$out) { @(($out -split "`r?`n") | Where-Object { $_ -match '^HEADLESS_OLD_PYREVIT \|' }) }

try {
    $py7 = Join-Path $Root 'user\pyRevit-Master'
    $old = Join-Path $Root 'ProgramFiles\pyRevit-Master'
    $py7core = New-Loader $py7 'netcore'; $py7fx = New-Loader $py7 'netfx'
    $oldcore = New-Loader $old 'netcore'; $oldfx = New-Loader $old 'netfx'

    # 1. Machine manifests name the old install (netcore + netfx), per-user ones name pyRevit 7:
    #    one info line for the one old install, all three years, exit 0 (info is not a problem).
    $m = Join-Path $Root 'c1\machine'; $u = Join-Path $Root 'c1\user'
    New-Manifest $m '2024' $oldfx; New-Manifest $m '2025' $oldcore; New-Manifest $m '2026' $oldcore
    foreach ($y in '2024', '2025', '2026') { New-Manifest $u $y $(if ($y -eq '2024') { $py7fx } else { $py7core }) }
    $r = Invoke-Doctor $m $u $py7
    $h = @(Get-HeadlessLines $r.Out)  # @(): a one-item result would otherwise unroll to a string
    Assert-True 'old machine install: one HEADLESS line' ($h.Count -eq 1) $r.Out
    Assert-True 'old machine install: info severity, all years, install folder' ($h.Count -eq 1 -and $h[0] -match '\| info \|' -and $h[0] -match 'Revit 2024, 2025, 2026' -and $h[0] -match [regex]::Escape('ProgramFiles\pyRevit-Master')) $r.Out
    Assert-True 'old machine install: exit 0' ($r.Code -eq 0) "exit $($r.Code)`n$($r.Out)"

    # 2. Machine manifests already name pyRevit 7: no HEADLESS line.
    $m = Join-Path $Root 'c2\machine'; $u = Join-Path $Root 'c2\user'
    New-Manifest $m '2026' $py7core; New-Manifest $u '2026' $py7core
    $r = Invoke-Doctor $m $u $py7
    Assert-True 'machine names pyRevit 7: no HEADLESS line' ((Get-HeadlessLines $r.Out).Count -eq 0) $r.Out

    # 3. No machine manifests at all: no HEADLESS line.
    $m = Join-Path $Root 'c3\machine'; $u = Join-Path $Root 'c3\user'
    New-Item -ItemType Directory -Force $m, $u | Out-Null
    $r = Invoke-Doctor $m $u $py7
    Assert-True 'no machine manifests: no HEADLESS line' ((Get-HeadlessLines $r.Out).Count -eq 0) $r.Out

    # 4. Machine manifest names a loader that no longer exists (old install removed): no HEADLESS line.
    $m = Join-Path $Root 'c4\machine'; $u = Join-Path $Root 'c4\user'
    New-Manifest $m '2026' (Join-Path $Root 'gone\bin\netcore\engines\IPY2712PR\pyRevitLoader.dll'); New-Manifest $u '2026' $py7core
    $r = Invoke-Doctor $m $u $py7
    Assert-True 'removed old install: no HEADLESS line' ((Get-HeadlessLines $r.Out).Count -eq 0) $r.Out
} finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Root
}

Write-Host ("{0} assertion(s), {1} failure(s)" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL: no assertions ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

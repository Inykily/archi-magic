<#
.SYNOPSIS
  Tests for the am-doctor YEAR_NOT_ATTACHED check (issue #88). Hermetic: temp machine and
  per-user Addins folders, a temp pyRevit 7 root with a loader file, and a temp Revit install
  root. Never touches the real manifests, never runs pyrevit.

  Scenario: Revit 2027 is installed but no year-2027 manifest exists anywhere.
    - The doctor reports YEAR_NOT_ATTACHED | warn for 2027 and exits 1.
    - A per-user 2027 manifest that loads the pyRevit 7 loader clears the finding.
    - A machine-wide 2027 manifest without a per-user override stays REPOINT_NEEDED, not
      YEAR_NOT_ATTACHED (the year HAS a manifest).
    - A year that is not installed at all is never reported, manifest or not.
  -Fix YEAR_NOT_ATTACHED runs am-pyrevit7-setup -Repoint -Verify (via a stub setup script).

  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-doctor\tests\test-year-not-attached.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Doctor = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\doctor.ps1')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-doctor-year-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Asserts = 0

function New-Loader([string]$installRoot) {
    $dll = Join-Path $installRoot 'bin\netcore\engines\IPY2712PR\pyRevitLoader.dll'
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
function Invoke-Doctor([string]$machine, [string]$user, [string]$py7, [string]$install, [string[]]$extra = @()) {
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Doctor -Only repoint -AddinsRoot $machine -UserAddinsRoot $user -Py7Root $py7 -RevitInstallRoot $install -LogDir (Join-Path $Root 'logs') @extra 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out }
}
function Assert-Case([string]$name, $r, [int]$code, [string]$pattern) {
    $script:Asserts++
    $ok = ($r.Code -eq $code) -and ($r.Out -match $pattern)
    if ($ok) { Write-Host "PASS $name (exit $($r.Code))" }
    else { $script:Fail++; Write-Host "FAIL $name : exit $($r.Code), want $code and /$pattern/`n$($r.Out)" }
}
function Assert-NoMatch([string]$name, [string]$out, [string]$pattern) {
    $script:Asserts++
    if ($out -notmatch $pattern) { Write-Host "PASS $name" }
    else { $script:Fail++; Write-Host "FAIL $name : output matches /$pattern/`n$out" }
}

try {
    $py7 = Join-Path $Root 'pyRevit-Master'
    $loader = New-Loader $py7
    $install = Join-Path $Root 'install'
    foreach ($y in '2026', '2027') { New-Item -ItemType Directory -Force (Join-Path $install "Revit $y") | Out-Null }

    # 1. 2027 installed, no manifest anywhere: YEAR_NOT_ATTACHED warn, exit 1.
    #    2026 is fully attached (machine + per-user), so it contributes no finding.
    $m = Join-Path $Root 'c1\machine'; $u = Join-Path $Root 'c1\user'
    New-Manifest $m '2026' (Join-Path $Root 'old\bin\netcore\engines\IPY2712PR\pyRevitLoader.dll')
    New-Manifest $u '2026' $loader
    $r = Invoke-Doctor $m $u $py7 $install
    Assert-Case '2027 installed, no manifest -> WARN + exit 1' $r 1 '(?m)^YEAR_NOT_ATTACHED \| warn \|.*2027'

    # 2. 2027 per-user manifest loads the pyRevit 7 loader: finding clears, exit 0.
    New-Manifest $u '2027' $loader
    $r = Invoke-Doctor $m $u $py7 $install
    Assert-Case '2027 per-user manifest -> exit 0' $r 0 '(?m)^REPOINT \| ok \|.*2026'
    Assert-NoMatch '2027 per-user manifest -> no YEAR_NOT_ATTACHED' $r.Out 'YEAR_NOT_ATTACHED'

    # 3. 2027 machine manifest, no per-user override: REPOINT_NEEDED, not YEAR_NOT_ATTACHED.
    $m3 = Join-Path $Root 'c3\machine'; $u3 = Join-Path $Root 'c3\user'
    New-Manifest $m3 '2026' (Join-Path $Root 'old\bin\netcore\engines\IPY2712PR\pyRevitLoader.dll')
    New-Manifest $u3 '2026' $loader
    New-Manifest $m3 '2027' (Join-Path $Root 'old\bin\netcore\engines\IPY2712PR\pyRevitLoader.dll')
    $r = Invoke-Doctor $m3 $u3 $py7 $install
    Assert-Case '2027 machine manifest, no override -> REPOINT_NEEDED' $r 1 '(?m)^REPOINT_NEEDED \| error \|.*2027'
    Assert-NoMatch '2027 machine manifest -> no YEAR_NOT_ATTACHED' $r.Out 'YEAR_NOT_ATTACHED'

    # 4. 2027 not installed: no finding even with no manifest anywhere for it.
    $install4 = Join-Path $Root 'install4'
    New-Item -ItemType Directory -Force (Join-Path $install4 'Revit 2026') | Out-Null
    $r = Invoke-Doctor $m $u $py7 $install4
    Assert-Case '2027 not installed -> exit 0' $r 0 '(?m)^REPOINT \| ok \|.*2026'
    Assert-NoMatch '2027 not installed -> no YEAR_NOT_ATTACHED' $r.Out 'YEAR_NOT_ATTACHED'

    # 5. -Fix YEAR_NOT_ATTACHED runs the setup script with -Repoint -Verify.
    $marker = Join-Path $Root 'fix-args.txt'
    $stubSetup = Join-Path $Root 'stub-setup.ps1'
    [IO.File]::WriteAllText($stubSetup, "`"fix args: `$(`$args -join ' ')`" | Out-File -LiteralPath '$marker' -Encoding ascii", (New-Object Text.UTF8Encoding $false))
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Doctor -Fix YEAR_NOT_ATTACHED -Py7Root $py7 -SetupScript $stubSetup -LogDir (Join-Path $Root 'logs') 2>&1 | Out-String
    $script:Asserts++
    $got = if (Test-Path -LiteralPath $marker) { [IO.File]::ReadAllText($marker) } else { '' }
    if (($LASTEXITCODE -eq 0) -and ($got -match '-Repoint -Verify')) { Write-Host 'PASS -Fix YEAR_NOT_ATTACHED runs setup -Repoint -Verify' }
    else { $script:Fail++; Write-Host "FAIL -Fix YEAR_NOT_ATTACHED: exit $LASTEXITCODE, marker '$got'`n$out" }
} finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Root
}

Write-Host ("{0} assertion(s), {1} failure(s)" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL: no assertions ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

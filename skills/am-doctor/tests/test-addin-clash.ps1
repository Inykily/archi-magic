<#
.SYNOPSIS
  Tests for the am-doctor per-user manifest checks of issue #258: ADDIN_NAME_CLASH,
  ADDIN_DUPLICATE, ADDIN_OTHER_ID and ADDIN_SHARED_ID. Hermetic: temp machine and per-user Addins
  folders, a temp pyRevit 7 root with a loader file, an empty temp Revit install root. Never
  touches the real manifests, never runs pyrevit or the real setup script.

  Cases (machine-wide 2026 pyRevit.addin with a test AddInId):
    1. per-user pyRevit.addin, same AddInId (what the old Repoint wrote) -> ADDIN_NAME_CLASH error, exit 1.
    2. per-user pyRevit7.addin, same AddInId (what Repoint writes now) -> REPOINT ok + ADDIN_SHARED_ID info, exit 0.
    3. per-user pyRevit.addin + pyRevit7.addin (+ a .disabled copy) -> ADDIN_DUPLICATE error that
       lists both and not the .disabled file, exit 1.
    4. per-user pyRevit7.addin with another AddInId -> ADDIN_OTHER_ID warn, exit 1.
    5. a per-user year with no machine-wide manifest and two manifests -> ADDIN_DUPLICATE, exit 1.
    6. -Fix ADDIN_NAME_CLASH and -Fix ADDIN_DUPLICATE run setup -Repoint -Verify (stub setup script).
    7. -Fix ADDIN_SHARED_ID has no automatic fix (exit 4).

  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-doctor\tests\test-addin-clash.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Doctor = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\doctor.ps1')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-doctor-addin-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$Id = '11111111-2222-3333-4444-555555555555'      # neutral test AddInId
$OtherId = '66666666-7777-8888-9999-AAAAAAAAAAAA'
$script:Fail = 0; $script:Asserts = 0

function Write-Manifest([string]$path, [string]$assembly, [string]$id) {
    New-Item -ItemType Directory -Force (Split-Path -Parent $path) | Out-Null
    $xml = "<?xml version=`"1.0`" encoding=`"utf-8`"?><RevitAddIns><AddIn Type=`"Application`"><Name>PyRevitLoader</Name><Assembly>$assembly</Assembly><AddInId>$id</AddInId></AddIn></RevitAddIns>"
    [IO.File]::WriteAllText($path, $xml, (New-Object Text.UTF8Encoding $false))
}
function Invoke-Doctor([string]$case, [string[]]$extra = @()) {
    $m = Join-Path $Root "$case\machine"; $u = Join-Path $Root "$case\user"
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Doctor -Only repoint -AddinsRoot $m -UserAddinsRoot $u -Py7Root $script:Py7 -RevitInstallRoot $script:EmptyInstall -LogDir (Join-Path $Root 'logs') @extra 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out }
}
function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name :`n$detail" }
}
function Get-Lines([string]$out, [string]$pattern) { @(($out -split "`r?`n") | Where-Object { $_ -match $pattern }) }
# A case folder with the machine-wide 2026 manifest of an old install.
function New-Case([string]$case) {
    Write-Manifest (Join-Path $Root "$case\machine\2026\pyRevit.addin") (Join-Path $Root 'old\bin\netcore\engines\IPY2712PR\pyRevitLoader.dll') $Id
    New-Item -ItemType Directory -Force (Join-Path $Root "$case\user") | Out-Null
    return (Join-Path $Root "$case\user")
}

try {
    New-Item -ItemType Directory -Force $Root | Out-Null
    $env:ARCHI_MAGIC_LOG_DIR = Join-Path $Root 'logs'   # keep test runs out of the real shared log
    $script:EmptyInstall = Join-Path $Root 'install-none'
    New-Item -ItemType Directory -Force $script:EmptyInstall | Out-Null
    $script:Py7 = Join-Path $Root 'pyRevit-Master'
    $loader = Join-Path $script:Py7 'bin\netcore\engines\IPY2712PR\pyRevitLoader.dll'
    New-Item -ItemType Directory -Force (Split-Path -Parent $loader) | Out-Null
    [IO.File]::WriteAllText($loader, 'stub')

    # 1. Same name + same AddInId: the layout that loaded no pyRevit on Revit 2026.4.
    $u = New-Case 'c1'
    Write-Manifest (Join-Path $u '2026\pyRevit.addin') $loader $Id
    $r = Invoke-Doctor 'c1'
    $l = @(Get-Lines $r.Out '^ADDIN_NAME_CLASH \| error \|')
    Assert-True '1: same name -> ADDIN_NAME_CLASH error, exit 1' ($r.Code -eq 1 -and $l.Count -eq 1 -and $l[0] -match 'same file name and the same AddInId' -and $l[0] -match 'Revit 2026') "exit $($r.Code)`n$($r.Out)"
    Assert-True '1: same name -> no REPOINT ok line for 2026' ((Get-Lines $r.Out '^REPOINT \| ok \|').Count -eq 0) $r.Out

    # 2. Own name + same AddInId: the layout Repoint writes now.
    $u = New-Case 'c2'
    Write-Manifest (Join-Path $u '2026\pyRevit7.addin') $loader $Id
    $r = Invoke-Doctor 'c2'
    Assert-True '2: pyRevit7.addin -> REPOINT ok, exit 0' ($r.Code -eq 0 -and (Get-Lines $r.Out '^REPOINT \| ok \|.*pyRevit7\.addin').Count -eq 1) "exit $($r.Code)`n$($r.Out)"
    Assert-True '2: pyRevit7.addin -> ADDIN_SHARED_ID info names the dialog' ((Get-Lines $r.Out "^ADDIN_SHARED_ID \| info \|.*Duplicated AddInId").Count -eq 1) $r.Out
    Assert-True '2: pyRevit7.addin -> no clash, duplicate or other-id line' ((Get-Lines $r.Out '^ADDIN_(NAME_CLASH|DUPLICATE|OTHER_ID) ').Count -eq 0) $r.Out

    # 3. Two per-user manifests (the state the issue found), plus a .disabled copy that Revit ignores.
    $u = New-Case 'c3'
    Write-Manifest (Join-Path $u '2026\pyRevit.addin') $loader $Id
    Write-Manifest (Join-Path $u '2026\pyRevit7.addin') $loader $Id
    Write-Manifest (Join-Path $u '2026\pyRevit.addin.disabled') $loader $Id
    $r = Invoke-Doctor 'c3'
    $l = @(Get-Lines $r.Out '^ADDIN_DUPLICATE \| error \|')
    Assert-True '3: two per-user manifests -> ADDIN_DUPLICATE lists both, exit 1' ($r.Code -eq 1 -and $l.Count -eq 1 -and $l[0] -match 'Revit 2026: 2 per-user' -and $l[0] -match 'pyRevit\.addin ->' -and $l[0] -match 'pyRevit7\.addin ->') "exit $($r.Code)`n$($r.Out)"
    Assert-True '3: the .disabled copy is not counted' ($l.Count -eq 1 -and $l[0] -notmatch '\.disabled') $r.Out

    # 4. Own name, another AddInId: Revit would load both pyRevit versions.
    $u = New-Case 'c4'
    Write-Manifest (Join-Path $u '2026\pyRevit7.addin') $loader $OtherId
    $r = Invoke-Doctor 'c4'
    Assert-True '4: another AddInId -> ADDIN_OTHER_ID warn, exit 1' ($r.Code -eq 1 -and (Get-Lines $r.Out '^ADDIN_OTHER_ID \| warn \|.*both pyRevit versions').Count -eq 1) "exit $($r.Code)`n$($r.Out)"

    # 5. A per-user-only year (no machine-wide manifest) with two manifests.
    $u = New-Case 'c5'
    Write-Manifest (Join-Path $u '2026\pyRevit7.addin') $loader $Id
    Write-Manifest (Join-Path $u '2027\pyRevit.addin') $loader $Id
    Write-Manifest (Join-Path $u '2027\pyRevit7.addin') $loader $Id
    $r = Invoke-Doctor 'c5'
    Assert-True '5: per-user-only year with two manifests -> ADDIN_DUPLICATE for 2027, exit 1' ($r.Code -eq 1 -and (Get-Lines $r.Out '^ADDIN_DUPLICATE \| error \|.*Revit 2027').Count -eq 1 -and (Get-Lines $r.Out '^ADDIN_DUPLICATE .*Revit 2026').Count -eq 0) "exit $($r.Code)`n$($r.Out)"

    # 6. -Fix runs the setup script with -Repoint -Verify.
    foreach ($code in 'ADDIN_NAME_CLASH', 'ADDIN_DUPLICATE', 'ADDIN_OTHER_ID') {
        $marker = Join-Path $Root "fix-$code.txt"
        $stubSetup = Join-Path $Root "stub-setup-$code.ps1"
        [IO.File]::WriteAllText($stubSetup, "`"fix args: `$(`$args -join ' ')`" | Out-File -LiteralPath '$marker' -Encoding ascii", (New-Object Text.UTF8Encoding $false))
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Doctor -Fix $code -Py7Root $script:Py7 -SetupScript $stubSetup -LogDir (Join-Path $Root 'logs') 2>&1 | Out-String
        $got = if (Test-Path -LiteralPath $marker) { [IO.File]::ReadAllText($marker) } else { '' }
        Assert-True "6: -Fix $code runs setup -Repoint -Verify" ($LASTEXITCODE -eq 0 -and $got -match '-Repoint -Verify') "exit $LASTEXITCODE, marker '$got'`n$out"
    }

    # 7. ADDIN_SHARED_ID is expected: no automatic fix.
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Doctor -Fix ADDIN_SHARED_ID -LogDir (Join-Path $Root 'logs') 2>&1 | Out-String
    Assert-True '7: -Fix ADDIN_SHARED_ID -> exit 4 (manual)' ($LASTEXITCODE -eq 4 -and $out -match 'no automatic fix') "exit $LASTEXITCODE`n$out"
} finally {
    Remove-Item Env:\ARCHI_MAGIC_LOG_DIR -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Root
}

Write-Host ("{0} assertion(s), {1} failure(s)" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL: no assertions ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

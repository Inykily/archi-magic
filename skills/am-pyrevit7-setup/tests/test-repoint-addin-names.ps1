<#
.SYNOPSIS
  Tests for issue #258: how -Repoint names the per-user manifest, and what -Verify reports.
  Hermetic: temp machine and per-user Addins roots, a temp pyRevit root with a loader file, an
  empty temp Revit install root, a temp backup root, and stub pyrevit/claude programs (stub.ps1).
  Never touches the real manifests, the real pyRevit config or the real MCP registration.

  Evidence from the issue (Revit 2026.4, IT pyRevit 6.4 for all users):
    same file name + same AddInId as the machine-wide pyRevit.addin -> "duplicated", no pyRevit tab;
    another file name + same AddInId -> pyRevit 7 loaded, the machine-wide one refused.
  So Repoint writes pyRevit7.addin with the machine-wide AddInId, and keeps one per-user manifest.

  Cases:
    A. Old layout: per-user pyRevit.addin (machine-wide name) + an older pyRevit7.addin + a
       .disabled copy. -Repoint -Verify: exit 0; only pyRevit7.addin is left, with the machine-wide
       AddInId and the pyRevit 7 loader; the .disabled file is untouched; the journal records
       pyRevit.addin as deleted with a byte backup; Verify names the expected AddInId dialog.
    B. -Verify on a per-user pyRevit.addin (machine-wide name): exit 6, name clash warning.
    C. -Verify on two per-user manifests: exit 6, "per-user pyRevit manifests" warning.
    D. -Verify on a per-user pyRevit7.addin with another AddInId: exit 6, "another AddInId".
    E. A year with no machine-wide manifest and two per-user manifests: -Repoint keeps
       pyRevit.addin (pyRevit's own name) and removes pyRevit7.addin.
    Mutation: Repoint that writes the machine-wide file name (the old code) goes RED on case A.

  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-pyrevit7-setup\tests\test-repoint-addin-names.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Setup = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\pyrevit7-setup.ps1')).Path
$Stub = (Resolve-Path (Join-Path $PSScriptRoot 'stub.ps1')).Path
$Base = Join-Path ([IO.Path]::GetTempPath()) ("am-setup-names-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$Id = '11111111-2222-3333-4444-555555555555'      # neutral test AddInId (machine-wide)
$OtherId = '66666666-7777-8888-9999-AAAAAAAAAAAA'
$Asm = 'bin\netfx\engines\IPY2712PR\pyRevitLoader.dll'
$script:Fail = 0; $script:Asserts = 0

function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name :`n$detail" }
}
function Get-Field([string]$path, [string]$tag) { [regex]::Match([IO.File]::ReadAllText($path), "<$tag>\s*(.*?)\s*</$tag>").Groups[1].Value }
function Get-Hash([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
function Write-Manifest([string]$path, [string]$assembly, [string]$id, [string]$note = '') {
    New-Item -ItemType Directory -Force (Split-Path -Parent $path) | Out-Null
    $xml = "<?xml version=`"1.0`" encoding=`"utf-8`" standalone=`"no`"?>`r`n<RevitAddIns>`r`n  <AddIn Type=`"Application`">`r`n    <Name>PyRevitLoader</Name>$note`r`n    <Assembly>$assembly</Assembly>`r`n    <AddInId>$id</AddInId>`r`n    <FullClassName>PyRevitLoader.PyRevitLoaderApplication</FullClassName>`r`n  </AddIn>`r`n</RevitAddIns>`r`n"
    [IO.File]::WriteAllText($path, $xml, (New-Object Text.UTF8Encoding $false))
}
# A fresh case folder: machine-wide 2026 manifest (old install), the 7.x loader, stubs. Returns the paths.
function New-Case([string]$name, [string]$setupPath = $Setup) {
    $root = Join-Path $Base $name
    $c = @{ Root = $root; Machine = (Join-Path $root 'machine'); User = (Join-Path $root 'user'); Py7Root = (Join-Path $root 'pyRevit-Master')
            Install = (Join-Path $root 'install-none'); Backups = (Join-Path $root 'backups'); StubDir = (Join-Path $root 'stub'); Setup = $setupPath }
    foreach ($d in $c.Machine, $c.User, $c.Py7Root, $c.Install, $c.Backups, $c.StubDir) { New-Item -ItemType Directory -Force $d | Out-Null }
    Write-Manifest (Join-Path $c.Machine '2026\pyRevit.addin') "C:\OldPyRevit\$Asm" $Id
    $c.Loader = Join-Path $c.Py7Root $Asm
    New-Item -ItemType Directory -Force (Split-Path -Parent $c.Loader) | Out-Null
    [IO.File]::WriteAllText($c.Loader, 'loader', (New-Object Text.UTF8Encoding $false))
    $c.Py7 = Join-Path $c.StubDir 'pyrevit.cmd'; $c.Claude = Join-Path $c.StubDir 'claude.cmd'
    "@set `"AM_STUB_ARGS=%*`"`r`n@powershell -NoProfile -ExecutionPolicy Bypass -File `"$Stub`" py7" | Set-Content -LiteralPath $c.Py7 -Encoding Ascii
    "@set `"AM_STUB_ARGS=%*`"`r`n@powershell -NoProfile -ExecutionPolicy Bypass -File `"$Stub`" claude" | Set-Content -LiteralPath $c.Claude -Encoding Ascii
    # Agent on, policy ask, MCP registered with this pyrevit stub: -Verify then judges only the manifests.
    $state = [ordered]@{ enabled = $true; policy = 'ask'; mcp = [ordered]@{ scope = 'user'; command = $c.Py7; args = 'mcp'; env = @() } }
    [IO.File]::WriteAllText((Join-Path $c.StubDir 'state.json'), ($state | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
    return $c
}
function Invoke-Setup($c, [string[]]$switches) {
    $env:AM_STUB_DIR = $c.StubDir; $env:AM_STUB_PY7 = $c.Py7
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $c.Setup @switches -UserAddinsRoot $c.User -MachineAddinsRoot $c.Machine -RevitInstallRoot $c.Install -Py7Root $c.Py7Root -Py7Exe $c.Py7 -ClaudeCli $c.Claude -BackupRoot $c.Backups 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out }
}
function Get-UserManifests($c, [string]$year) { @(Get-ChildItem (Join-Path (Join-Path $c.User $year) 'pyRevit*.addin') -ErrorAction SilentlyContinue | ForEach-Object { $_.Name } | Sort-Object) }

# Case A as a function, so the mutation run can reuse it. Returns the list of failed checks.
function Test-CaseA([string]$name, [string]$setupPath) {
    $bad = New-Object System.Collections.Generic.List[string]
    $c = New-Case $name $setupPath
    $old = Join-Path $c.User '2026\pyRevit.addin'
    Write-Manifest $old $c.Loader $Id                                   # what the old Repoint wrote
    Write-Manifest (Join-Path $c.User '2026\pyRevit7.addin') $c.Loader $Id '<!-- older copy -->'
    $disabled = Join-Path $c.User '2026\pyRevit.addin.disabled'
    Write-Manifest $disabled "C:\OldPyRevit\$Asm" $Id
    $oldHash = Get-Hash $old; $disHash = Get-Hash $disabled
    $r = Invoke-Setup $c @('-Repoint', '-Verify')
    if ($r.Code -ne 0) { $bad.Add("exit $($r.Code), want 0`n$($r.Out)") }
    $left = Get-UserManifests $c '2026'
    if (($left -join ',') -ne 'pyRevit7.addin') { $bad.Add("per-user 2026 manifests: '$($left -join ',')', want only pyRevit7.addin") }
    $kept = Join-Path $c.User '2026\pyRevit7.addin'
    if (Test-Path -LiteralPath $kept) {
        if ((Get-Field $kept 'AddInId') -ne $Id) { $bad.Add("pyRevit7.addin AddInId '$(Get-Field $kept 'AddInId')', want the machine-wide $Id") }
        if ((Get-Field $kept 'Assembly') -ne $c.Loader) { $bad.Add("pyRevit7.addin Assembly '$(Get-Field $kept 'Assembly')', want $($c.Loader)") }
    }
    if (-not (Test-Path -LiteralPath $disabled) -or (Get-Hash $disabled) -ne $disHash) { $bad.Add('the .disabled file changed or is gone') }
    $journal = @(Get-ChildItem $c.Backups -Recurse -Filter journal.json)
    $del = $null
    if ($journal.Count -eq 1) { $del = @(([IO.File]::ReadAllText($journal[0].FullName) | ConvertFrom-Json).manifests | Where-Object { $_.action -eq 'deleted' -and "$($_.path)" -like '*\2026\pyRevit.addin' }) }
    if (-not $del -or $del.Count -ne 1) { $bad.Add("journal has no 'deleted' entry for 2026\pyRevit.addin ($($journal.Count) journal(s))") }
    elseif (-not (Test-Path -LiteralPath $del[0].backup) -or (Get-Hash $del[0].backup) -ne $oldHash) { $bad.Add('the backup of 2026\pyRevit.addin is missing or not byte-identical') }
    if ($r.Out -notmatch 'Duplicated AddInId') { $bad.Add("Verify did not name the expected 'Duplicated AddInId' dialog`n$($r.Out)") }
    return , $bad
}

try {
    New-Item -ItemType Directory -Force $Base | Out-Null
    $env:ARCHI_MAGIC_LOG_DIR = Join-Path $Base 'logs'   # keep test runs out of the real shared log

    # A.
    $p = Test-CaseA 'a' $Setup
    Assert-True 'A: old layout -> one pyRevit7.addin, machine-wide AddInId, journaled delete, exit 0' ($p.Count -eq 0) ($p -join "`n")

    # B.
    $c = New-Case 'b'
    Write-Manifest (Join-Path $c.User '2026\pyRevit.addin') $c.Loader $Id
    $r = Invoke-Setup $c @('-Verify')
    Assert-True 'B: -Verify, per-user pyRevit.addin -> exit 6 + name clash' ($r.Code -eq 6 -and $r.Out -match 'same file name as the machine-wide manifest') "exit $($r.Code)`n$($r.Out)"

    # C.
    $c = New-Case 'c'
    Write-Manifest (Join-Path $c.User '2026\pyRevit7.addin') $c.Loader $Id
    Write-Manifest (Join-Path $c.User '2026\pyRevit-extra.addin') $c.Loader $Id
    $r = Invoke-Setup $c @('-Verify')
    Assert-True 'C: -Verify, two per-user manifests -> exit 6 + warning' ($r.Code -eq 6 -and $r.Out -match '2 per-user pyRevit manifests') "exit $($r.Code)`n$($r.Out)"

    # D.
    $c = New-Case 'd'
    Write-Manifest (Join-Path $c.User '2026\pyRevit7.addin') $c.Loader $OtherId
    $r = Invoke-Setup $c @('-Verify')
    Assert-True 'D: -Verify, another AddInId -> exit 6 + warning' ($r.Code -eq 6 -and $r.Out -match 'another AddInId') "exit $($r.Code)`n$($r.Out)"
    $c = New-Case 'd2'
    Write-Manifest (Join-Path $c.User '2026\pyRevit7.addin') $c.Loader $Id
    $r = Invoke-Setup $c @('-Verify')
    Assert-True 'D: -Verify, own name + same AddInId -> exit 0 (negative control)' ($r.Code -eq 0) "exit $($r.Code)`n$($r.Out)"

    # E.
    $c = New-Case 'e'
    Write-Manifest (Join-Path $c.User '2027\pyRevit.addin') $c.Loader $Id
    Write-Manifest (Join-Path $c.User '2027\pyRevit7.addin') $c.Loader $Id
    $r = Invoke-Setup $c @('-Repoint')
    $left = Get-UserManifests $c '2027'
    Assert-True 'E: no machine-wide 2027, two per-user -> keeps pyRevit.addin only' ($r.Code -eq 0 -and ($left -join ',') -eq 'pyRevit.addin') "exit $($r.Code), left '$($left -join ',')'`n$($r.Out)"

    # Mutation: the old Repoint wrote the machine-wide file name.
    $src = [IO.File]::ReadAllText($Setup)
    $needle = '$dstName = $UserManifestName'
    if (-not $src.Contains($needle)) { throw 'mutation anchor not found in pyrevit7-setup.ps1' }
    $mut = Join-Path $Base 'pyrevit7-setup.same-name.ps1'
    [IO.File]::WriteAllText($mut, $src.Replace($needle, '$dstName = $src.Name'), (New-Object Text.UTF8Encoding $false))
    $pm = Test-CaseA 'mutant' $mut
    Assert-True 'mutation: Repoint with the machine-wide file name goes RED on case A' ($pm.Count -gt 0 -and @($pm | Where-Object { $_ -match 'want only pyRevit7.addin' }).Count -eq 1) ($pm -join "`n")
} finally {
    Remove-Item Env:\AM_STUB_DIR, Env:\AM_STUB_PY7, Env:\ARCHI_MAGIC_LOG_DIR -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Base -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host ("{0} assertion(s), {1} failure(s)" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL: no assertions ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

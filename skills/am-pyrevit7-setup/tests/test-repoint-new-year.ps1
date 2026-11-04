<#
.SYNOPSIS
  Tests for pyrevit7-setup.ps1 -Repoint on a Revit year installed after setup (issue #88).
  Hermetic: temp machine and per-user Addins roots, a temp pyRevit root with a loader file,
  a temp Revit install root, a temp backup root, and stub pyrevit/claude programs (stub.ps1).
  Never touches the real manifests, the real pyRevit config or the real MCP registration.

  Scenario: machine-wide manifests for 2025 and 2026 (IT install), a per-user manifest for
  2026 only, Revit 2025/2026/2027 installed. -Repoint must:
    - rewrite the 2025/2026 per-user manifests from the machine sources,
    - attach 2027 per-user (pyrevit attach master default 2027) and write its manifest,
    - never attach 2025 or 2026.
  A second -Repoint must leave the 2027 manifest byte-identical and attach nothing new.
  The first run's journal must record the 2027 manifest as created (so -Undo deletes it).

  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-pyrevit7-setup\tests\test-repoint-new-year.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Setup = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\pyrevit7-setup.ps1')).Path
$Stub = (Resolve-Path (Join-Path $PSScriptRoot 'stub.ps1')).Path
$Base = Join-Path ([IO.Path]::GetTempPath()) ("am-setup-newyear-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Asserts = 0

function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name :`n$detail" }
}
function Get-Assembly([string]$path) {
    return ([regex]::Match([IO.File]::ReadAllText($path), '<Assembly>\s*(.*?)\s*</Assembly>').Groups[1].Value)
}
function Invoke-Setup([string[]]$switches, [string]$root) {
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Setup @switches -UserAddinsRoot (Join-Path $root 'user') -MachineAddinsRoot (Join-Path $root 'machine') -RevitInstallRoot (Join-Path $root 'install') -Py7Root (Join-Path $root 'pyRevit-Master') -Py7Exe (Join-Path $root 'stub\pyrevit.cmd') -ClaudeCli (Join-Path $root 'stub\claude.cmd') -BackupRoot (Join-Path $root 'backups') 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out }
}

try {
    $machine = Join-Path $Base 'machine'; $user = Join-Path $Base 'user'
    $py7Root = Join-Path $Base 'pyRevit-Master'; $install = Join-Path $Base 'install'
    $backups = Join-Path $Base 'backups'; $stubDir = Join-Path $Base 'stub'
    foreach ($d in $machine, $user, $py7Root, $install, $backups, $stubDir) { New-Item -ItemType Directory -Force $d | Out-Null }

    # Machine-wide manifests (IT install) for 2025 and 2026, and the 7.x loader they point to.
    $asm = 'bin\netfx\engines\IPY2712PR\pyRevitLoader.dll'
    foreach ($y in '2025', '2026') {
        New-Item -ItemType Directory -Force (Join-Path $machine $y) | Out-Null
        $xml = "<?xml version=`"1.0`" encoding=`"utf-8`"?><RevitAddIns><AddIn Type=`"Application`"><Name>PyRevitLoader</Name><Assembly>C:\OldPyRevit\$asm</Assembly></AddIn></RevitAddIns>"
        [IO.File]::WriteAllText((Join-Path $machine "$y\pyRevit.addin"), $xml, (New-Object Text.UTF8Encoding $false))
    }
    $loader = Join-Path $py7Root $asm
    New-Item -ItemType Directory -Force (Split-Path -Parent $loader) | Out-Null
    [IO.File]::WriteAllText($loader, 'loader', (New-Object Text.UTF8Encoding $false))

    # Per-user manifest for 2026 only, pointing at an old install: Repoint replaces it.
    New-Item -ItemType Directory -Force (Join-Path $user '2026') | Out-Null
    $oldUser = "<?xml version=`"1.0`" encoding=`"utf-8`"?><RevitAddIns><AddIn Type=`"Application`"><Assembly>C:\Users\x\AppData\Roaming\pyRevit-6\$asm</Assembly></AddIn></RevitAddIns>"
    [IO.File]::WriteAllText((Join-Path $user '2026\pyRevit.addin'), $oldUser, (New-Object Text.UTF8Encoding $false))

    # Revit 2025/2026/2027 installed; 2027 has no manifest anywhere.
    foreach ($y in '2025', '2026', '2027') { New-Item -ItemType Directory -Force (Join-Path $install "Revit $y") | Out-Null }

    # Stub programs and their starting state.
    $py7 = Join-Path $stubDir 'pyrevit.cmd'; $claude = Join-Path $stubDir 'claude.cmd'
    "@set `"AM_STUB_ARGS=%*`"`r`n@powershell -NoProfile -ExecutionPolicy Bypass -File `"$Stub`" py7" | Set-Content -LiteralPath $py7 -Encoding Ascii
    "@set `"AM_STUB_ARGS=%*`"`r`n@powershell -NoProfile -ExecutionPolicy Bypass -File `"$Stub`" claude" | Set-Content -LiteralPath $claude -Encoding Ascii
    $state0 = '{"enabled":true,"policy":"ask","mcp":null}'
    [IO.File]::WriteAllText((Join-Path $stubDir 'state.json'), $state0, (New-Object Text.UTF8Encoding $false))
    $env:AM_STUB_DIR = $stubDir; $env:AM_STUB_PY7 = $py7
    $env:AM_STUB_USER_ADDINS = $user; $env:AM_STUB_PY7_LOADER = $loader

    # First -Repoint.
    $r = Invoke-Setup @('-Repoint') $Base
    Assert-True 'first -Repoint exit 0' ($r.Code -eq 0) "exit $($r.Code)`n$($r.Out)"
    $man2027 = Join-Path $user '2027\pyRevit.addin'
    Assert-True '2027 manifest created' (Test-Path -LiteralPath $man2027) $r.Out
    Assert-True '2027 manifest points at the pyRevit 7 loader' ((Test-Path -LiteralPath $man2027) -and (Get-Assembly $man2027) -eq $loader) $(if (Test-Path -LiteralPath $man2027) { Get-Assembly $man2027 } else { '(missing)' })
    $calls = if (Test-Path -LiteralPath (Join-Path $stubDir 'calls.log')) { [IO.File]::ReadAllLines((Join-Path $stubDir 'calls.log')) } else { @() }
    $attach27 = @($calls | Where-Object { $_ -match 'attach master default 2027' })
    $attachOther = @($calls | Where-Object { $_ -match 'attach master default 202[56]' })
    Assert-True 'attach called exactly once for 2027' ($attach27.Count -eq 1) ($calls -join "`n")
    Assert-True 'attach never called for 2025/2026' ($attachOther.Count -eq 0) ($calls -join "`n")
    Assert-True '2025 manifest rewritten to the pyRevit 7 loader' ((Test-Path -LiteralPath (Join-Path $user '2025\pyRevit.addin')) -and (Get-Assembly (Join-Path $user '2025\pyRevit.addin')) -eq $loader) $r.Out
    Assert-True '2026 manifest replaced with the pyRevit 7 loader' ((Get-Assembly (Join-Path $user '2026\pyRevit.addin')) -eq $loader) $(Get-Assembly (Join-Path $user '2026\pyRevit.addin'))

    # The first run's journal records the 2027 manifest as created (so -Undo deletes it).
    $journals = @(Get-ChildItem $backups -Directory -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName 'journal.json' } | Where-Object { Test-Path -LiteralPath $_ })
    $created27 = $false
    foreach ($j in $journals) {
        try {
            $o = [IO.File]::ReadAllText($j) | ConvertFrom-Json
            foreach ($e in @($o.manifests)) {
                if ($e.action -eq 'created' -and "$($e.path)" -match '2027') { $created27 = $true }
            }
        } catch { }
    }
    Assert-True 'journal records 2027 manifest as created' $created27 "journals: $($journals -join ', ')"

    # Second -Repoint: 2027 manifest byte-identical, no new attach.
    $hashBefore = (Get-FileHash -LiteralPath $man2027 -Algorithm SHA256).Hash
    $r2 = Invoke-Setup @('-Repoint') $Base
    Assert-True 'second -Repoint exit 0' ($r2.Code -eq 0) "exit $($r2.Code)`n$($r2.Out)"
    $hashAfter = (Get-FileHash -LiteralPath $man2027 -Algorithm SHA256).Hash
    Assert-True 'second -Repoint leaves the 2027 manifest byte-identical' ($hashBefore -eq $hashAfter) "before $hashBefore, after $hashAfter"
    $calls2 = [IO.File]::ReadAllLines((Join-Path $stubDir 'calls.log'))
    $attach27b = @($calls2 | Where-Object { $_ -match 'attach master default 2027' })
    Assert-True 'second -Repoint attaches nothing new' ($attach27b.Count -eq 1) ($calls2 -join "`n")
} finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Base
}

Write-Host ("{0} assertion(s), {1} failure(s)" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL: no assertions ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

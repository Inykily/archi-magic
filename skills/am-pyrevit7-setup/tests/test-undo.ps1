<#
.SYNOPSIS
  Tests for pyrevit7-setup.ps1 -Undo. Hermetic: temp Revit addins roots, a temp pyRevit root,
  a temp backup root, and stub pyrevit/claude programs (stub.ps1). Never touches the real
  per-user manifests, the real pyRevit config or the real Claude Code MCP registration.

  Scenario: setup -Repoint -EnableAgent, then -Undo.
    - Revit 2026 has a per-user manifest before (UTF-8 BOM, CRLF, one non-ASCII char) -> replaced,
      then restored byte-identical (SHA256).
    - Revit 2025 has none before -> created, then deleted (folder too).
    - Agent: Disabled + policy 'auto' before -> enabled + 'ask', then restored.
    - MCP: user-scope registration with another command before -> replaced, then restored.
    - A second -Undo exits 7 (nothing left to undo).
  Mutation: the same scenario with an undo that restores through text (ReadAllText/WriteAllText)
  must go RED on the byte-identical check (and the script's own checksum check makes undo exit 8).

  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-pyrevit7-setup\tests\test-undo.ps1
#>
$ErrorActionPreference = 'Stop'
$Setup = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\pyrevit7-setup.ps1')).Path
$Stub = (Resolve-Path (Join-Path $PSScriptRoot 'stub.ps1')).Path
$Base = Join-Path ([IO.Path]::GetTempPath()) ("am-setup-undo-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Asserts = 0

function Check([bool]$cond, [string]$msg, [System.Collections.Generic.List[string]]$problems) {
    $script:Asserts++
    if (-not $cond) { $problems.Add($msg) }
}

function Invoke-Scenario([string]$setupPath, [string]$root) {
    $problems = New-Object System.Collections.Generic.List[string]
    $machine = Join-Path $root 'machine'; $user = Join-Path $root 'user'; $py7Root = Join-Path $root 'pyRevit-Master'
    $backups = Join-Path $root 'backups'; $stubDir = Join-Path $root 'stub'
    foreach ($d in $machine, $user, $py7Root, $backups, $stubDir) { New-Item -ItemType Directory -Force $d | Out-Null }

    # Machine-wide manifests (IT install) for 2025 and 2026, and the 7.x loader they will point to.
    $asm = 'bin\netfx\engines\IPY2712PR\pyRevitLoader.dll'
    foreach ($y in '2025', '2026') {
        New-Item -ItemType Directory -Force (Join-Path $machine $y) | Out-Null
        $xml = "<?xml version=`"1.0`" encoding=`"utf-8`"?>`r`n<RevitAddIns><AddIn Type=`"Application`"><Name>PyRevitLoader</Name><Assembly>C:\OldPyRevit\$asm</Assembly></AddIn></RevitAddIns>`r`n"
        [IO.File]::WriteAllText((Join-Path $machine "$y\pyRevit.addin"), $xml, (New-Object Text.UTF8Encoding $false))
    }
    New-Item -ItemType Directory -Force (Split-Path (Join-Path $py7Root $asm)) | Out-Null
    [IO.File]::WriteAllText((Join-Path $py7Root $asm), 'loader', (New-Object Text.UTF8Encoding $false))

    # Original per-user manifest for 2026 only: BOM + CRLF + a non-ASCII char, so a text round trip changes bytes.
    New-Item -ItemType Directory -Force (Join-Path $user '2026') | Out-Null
    $orig = Join-Path $user '2026\pyRevit.addin'
    $origText = "<?xml version=`"1.0`" encoding=`"utf-8`"?>`r`n<!-- Caf" + [char]0xE9 + " -->`r`n<RevitAddIns><AddIn Type=`"Application`"><Assembly>C:\Users\x\AppData\Roaming\pyRevit-6\$asm</Assembly></AddIn></RevitAddIns>`r`n"
    [IO.File]::WriteAllText($orig, $origText, (New-Object Text.UTF8Encoding $true))
    $origHash = (Get-FileHash -LiteralPath $orig -Algorithm SHA256).Hash

    # Stub programs and their starting state.
    $py7 = Join-Path $stubDir 'pyrevit.cmd'; $claude = Join-Path $stubDir 'claude.cmd'
    "@set `"AM_STUB_ARGS=%*`"`r`n@powershell -NoProfile -ExecutionPolicy Bypass -File `"$Stub`" py7" | Set-Content -LiteralPath $py7 -Encoding Ascii
    "@set `"AM_STUB_ARGS=%*`"`r`n@powershell -NoProfile -ExecutionPolicy Bypass -File `"$Stub`" claude" | Set-Content -LiteralPath $claude -Encoding Ascii
    $state0 = '{"enabled":false,"policy":"auto","mcp":{"scope":"user","command":"C:\\Old\\pyrevit.exe","args":"mcp","env":[]}}'
    [IO.File]::WriteAllText((Join-Path $stubDir 'state.json'), $state0, (New-Object Text.UTF8Encoding $false))
    $env:AM_STUB_DIR = $stubDir; $env:AM_STUB_PY7 = $py7

    $common = @('-UserAddinsRoot', $user, '-MachineAddinsRoot', $machine, '-Py7Root', $py7Root, '-Py7Exe', $py7, '-ClaudeCli', $claude, '-BackupRoot', $backups)
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setupPath -Repoint -EnableAgent @common 2>&1 | Out-String
    $code = $LASTEXITCODE
    Check ($code -eq 0) "setup exit $code`n$out" $problems
    Check ((Get-FileHash -LiteralPath $orig -Algorithm SHA256).Hash -ne $origHash) 'setup did not change the 2026 manifest' $problems
    Check (Test-Path (Join-Path $user '2025\pyRevit.addin')) 'setup did not create the 2025 manifest' $problems
    $journals = @(Get-ChildItem $backups -Recurse -Filter journal.json)
    Check ($journals.Count -eq 1) "expected 1 journal, found $($journals.Count): $((Get-ChildItem $backups -Recurse | ForEach-Object FullName) -join ', ')`n$out" $problems
    if ($journals.Count -eq 1) {
        $j = [IO.File]::ReadAllText($journals[0].FullName) | ConvertFrom-Json
        Check ((@($j.manifests | ForEach-Object action) | Sort-Object) -join ',' -eq 'created,replaced') "journal actions: $(@($j.manifests | ForEach-Object action) -join ',')" $problems
        Check ($j.mcp.action -eq 'replaced' -and $j.mcp.previous.command -eq 'C:\Old\pyrevit.exe') 'journal MCP entry' $problems
        Check ($j.agent.wasEnabled -eq $false -and $j.agent.policy -eq 'auto') 'journal agent entry' $problems
    }
    $mid = [IO.File]::ReadAllText((Join-Path $stubDir 'state.json')) | ConvertFrom-Json
    Check ($mid.enabled -eq $true -and $mid.policy -eq 'ask' -and $mid.mcp.command -eq $py7) "state after setup: $($mid | ConvertTo-Json -Compress -Depth 5)" $problems

    # A no-op re-run (what users do after a pyRevit update) must not write a journal, so -Undo
    # still reverses the run that made the changes.
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setupPath -Repoint -EnableAgent @common 2>&1 | Out-String
    Check ($LASTEXITCODE -eq 0) "re-run exit $LASTEXITCODE`n$out" $problems
    $journals = @(Get-ChildItem $backups -Recurse -Filter journal.json)
    Check ($journals.Count -eq 1) "no-op re-run wrote a journal: $($journals.Count) journal(s)" $problems

    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setupPath -Undo @common 2>&1 | Out-String
    $code = $LASTEXITCODE
    Check ($code -eq 0) "undo exit $code`n$out" $problems
    $nowHash = if (Test-Path $orig) { (Get-FileHash -LiteralPath $orig -Algorithm SHA256).Hash } else { 'missing' }
    Check ($nowHash -eq $origHash) "2026 manifest not byte-identical after undo ($nowHash vs $origHash)" $problems
    Check (-not (Test-Path (Join-Path $user '2025'))) '2025 manifest or folder still present after undo' $problems
    $end = [IO.File]::ReadAllText((Join-Path $stubDir 'state.json')) | ConvertFrom-Json
    $want = $state0 | ConvertFrom-Json
    Check (($end | ConvertTo-Json -Compress -Depth 5) -eq ($want | ConvertTo-Json -Compress -Depth 5)) "stub state after undo $($end | ConvertTo-Json -Compress -Depth 5)" $problems
    Check ($out -match "previous agent policy was 'auto'") 'undo did not warn about restoring auto' $problems

    $out2 = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setupPath -Undo @common 2>&1 | Out-String
    Check ($LASTEXITCODE -eq 7) "second undo exit $LASTEXITCODE (want 7)" $problems
    return ,$problems
}

try {
    New-Item -ItemType Directory -Force $Base | Out-Null
    $env:ARCHI_MAGIC_LOG_DIR = Join-Path $Base 'logs'   # keep test runs out of the real shared log
    $p = Invoke-Scenario $Setup (Join-Path $Base 'real')
    if ($p.Count -eq 0) { Write-Host 'PASS write -> undo restores byte-identical originals, MCP and agent state' }
    else { $script:Fail++; Write-Host "FAIL real script:`n  - $($p -join "`n  - ")" }

    # Mutation: restore the replaced manifest through text instead of a byte copy.
    $mut = Join-Path $Base 'pyrevit7-setup.mutant.ps1'
    $src = [IO.File]::ReadAllText($Setup)
    $needle = 'Copy-Item -LiteralPath $m.backup -Destination $p -Force
                if ((Get-Sha256 $p) -ne $m.backupSha256)'
    if (-not $src.Contains($needle)) { $needle = $needle -replace "`n", "`r`n" }
    if (-not $src.Contains($needle)) { throw 'mutation anchor not found in pyrevit7-setup.ps1' }
    $src = $src.Replace($needle, ($needle -replace 'Copy-Item -LiteralPath \$m\.backup -Destination \$p -Force', '[IO.File]::WriteAllText($p, [IO.File]::ReadAllText($m.backup))'))
    [IO.File]::WriteAllText($mut, $src, (New-Object Text.UTF8Encoding $false))
    $pm = Invoke-Scenario $mut (Join-Path $Base 'mutant')
    $script:Asserts++
    if ($pm.Count -gt 0 -and @($pm | Where-Object { $_ -match 'not byte-identical' }).Count -eq 1 -and @($pm | Where-Object { $_ -notmatch 'not byte-identical|^undo exit 8' }).Count -eq 0) { Write-Host 'PASS mutation (text-mode restore) goes RED on the byte-identical check' }
    else { $script:Fail++; Write-Host "FAIL mutation stayed green: $($pm -join '; ')" }
} finally {
    Remove-Item Env:\AM_STUB_DIR, Env:\AM_STUB_PY7, Env:\ARCHI_MAGIC_LOG_DIR -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Base -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "$script:Asserts assertion(s), $script:Fail failed"
if ($script:Fail -or $script:Asserts -eq 0) { exit 1 }
exit 0

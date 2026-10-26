<#
.SYNOPSIS
  Mutation table for the repo checks (rule: a guard never seen failing is not a guard). Each case
  copies the repo to a temp folder, applies one change, and runs the check there with -Root:
    - every "break" case must turn the check red (exit non-zero, expected message),
    - every "legitimate" case must stay green, including a full simulated split
      (docs/plans/2026-10-24-plugin-split.md), so the checks do not block the real split.
  Never touches this checkout. Needs no network.

  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\test-checks.ps1
  Exit 0 = every case behaves as expected.
#>
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Base = Join-Path ([IO.Path]::GetTempPath()) ("am-checks-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Cases = 0
$utf8 = New-Object Text.UTF8Encoding $false

function New-Tree([string]$name) {
    $t = Join-Path $Base $name
    # Copy the tracked layout only; skip git data, dependencies and agent worktrees.
    & robocopy $Repo $t /E /NFL /NDL /NJH /NJS /NP /XD .git node_modules .claude | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) for $name" }
    return $t
}
function Invoke-Check([string]$script, [string]$root, [string[]]$extra = @()) {
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts\$script") @extra 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out }
}
function Expect([string]$name, $r, [bool]$wantRed, [string]$pattern) {
    $script:Cases++
    $red = $r.Code -ne 0
    $ok = ($red -eq $wantRed) -and ($r.Out -match $pattern)
    if ($ok) { Write-Host ("PASS {0} ({1})" -f $name, $(if ($red) { 'red' } else { 'green' })) }
    else { $script:Fail++; Write-Host ("FAIL {0} : exit {1}, want {2} and /{3}/`n{4}" -f $name, $r.Code, $(if ($wantRed) { 'red' } else { 'green' }), $pattern, $r.Out) }
}
function Set-Text([string]$path, [string]$text) {
    $d = Split-Path -Parent $path; if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force $d | Out-Null }
    [IO.File]::WriteAllText($path, $text, $utf8)
}
function Add-MarketEntry([string]$root, [string]$name, [string]$source) {
    $p = Join-Path $root '.claude-plugin\marketplace.json'
    $m = [IO.File]::ReadAllText($p) | ConvertFrom-Json
    $m.plugins = @($m.plugins) + @([pscustomobject]@{ name = $name; source = $source; description = 'test' })
    Set-Text $p ($m | ConvertTo-Json -Depth 10)
}

try {
    New-Item -ItemType Directory -Force $Base | Out-Null

    # 0. Control: the unchanged tree is green for every check.
    $t = New-Tree 'control'
    Expect 'control: check-skills green' (Invoke-Check 'check-skills.ps1' $t) $false 'PASS'
    Expect 'control: check-version-bump green' (Invoke-Check 'check-version-bump.ps1' $t) $false 'PASS'
    Expect 'control: sync-house-rules green' (Invoke-Check 'sync-house-rules.ps1' $t) $false 'unchanged'

    # 1. Break: a shared-file copy drifts from its source.
    $t = New-Tree 'm1'
    Add-Content -LiteralPath (Join-Path $t 'skills\am-bim-viewer\viewer\viewer-core.mjs') -Value '// drift'
    Expect 'break: shared copy drifted -> red' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $true 'viewer-core\.mjs : differs'

    # 2. Break: a shared-file copy is missing.
    $t = New-Tree 'm2'
    Remove-Item -LiteralPath (Join-Path $t 'skills\am-bim-viewer\viewer\demo.json')
    Expect 'break: shared copy missing -> red' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $true 'demo\.json : shared-file copy is missing'

    # 3. Break: a skill names another with the old namespace.
    $t = New-Tree 'm3'
    $md = Join-Path $t 'skills\am-grill-me\SKILL.md'
    Set-Text $md (([IO.File]::ReadAllText($md)) -replace 'Call the Skill tool with "am-grilling"', 'Call the Skill tool with "archi-magic:am-grilling"')
    Expect 'break: archi-magic:am- reference -> red' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $true "names a skill as 'archi-magic:am-"

    # 4. Break: the rules hook in two hooks.json files.
    $t = New-Tree 'm4'
    Copy-Item (Join-Path $t 'hooks') (Join-Path $t 'plugins\core\hooks') -Recurse
    Expect 'break: rules hook twice -> red' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $true 'it must be in exactly one'

    # 5. Break: split manifest name differs from its marketplace entry.
    $t = New-Tree 'm5'
    Set-Text (Join-Path $t 'plugins\core\.claude-plugin\plugin.json') '{ "name": "archi-magic-kore" }'
    Add-MarketEntry $t 'archi-magic-core' './plugins/core'
    Expect 'break: manifest name != entry name -> red' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $true "differs from marketplace entry name 'archi-magic-core'"

    # 6. Break: split skills exist while the root skills/ folder remains.
    $t = New-Tree 'm6'
    Copy-Item (Join-Path $t 'skills\am-grilling') (Join-Path $t 'plugins\core\skills\am-grilling') -Recurse
    Expect 'break: root skills/ left after split -> red' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $true 'the root skills/ folder must be gone'

    # 7. Break: a split plugin pins a version.
    $t = New-Tree 'm7'
    Set-Text (Join-Path $t 'plugins\core\.claude-plugin\plugin.json') '{ "name": "archi-magic-core", "version": "1.0.0" }'
    Expect 'break: split manifest pins version -> red' (Invoke-Check 'check-version-bump.ps1' $t) $true 'pins "version"'

    # 8. Break: sync-house-rules finds no SKILL.md (a wrong layout must not pass silently).
    $t = New-Tree 'm8'
    Remove-Item -Recurse -Force (Join-Path $t 'skills')
    Expect 'break: sync-house-rules zero matches -> red' (Invoke-Check 'sync-house-rules.ps1' $t) $true 'no SKILL.md found'

    # 8b. Break: a Rhino script prints bare JSON (Rhino noise lines make it unparseable).
    $t = New-Tree 'm8b'
    $py = Join-Path $t 'skills\am-rhino-model-health\scripts\rhino_health.py'
    Set-Text $py (([IO.File]::ReadAllText($py)) -replace 'print\(RESULT_PREFIX \+ json\.dumps\(main', 'print(json.dumps(main')
    Expect 'break: Rhino print without prefix -> red' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $true 'prints without RESULT_PREFIX'

    # 8c. Break: a Rhino script loses its RESULT_PREFIX constant.
    $t = New-Tree 'm8c'
    $py = Join-Path $t 'skills\am-rhino-area-report\scripts\rhino_area_report.py'
    Set-Text $py (([IO.File]::ReadAllText($py)) -replace 'RESULT_PREFIX = "AM_RESULT "', 'RESULT_PREFIX = "RESULT "')
    Expect 'break: wrong RESULT_PREFIX -> red' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $true 'must define RESULT_PREFIX'

    # 8d. Break: a skill script opens a file outside "with" (locks the file in Revit).
    $t = New-Tree 'm8d'
    $py = Join-Path $t 'skills\am-safe-change\scripts\read_elements.py'
    Set-Text $py (([IO.File]::ReadAllText($py)) -replace 'with io\.open\(path, "r", encoding="utf-8-sig"\) as f:', 'f = io.open(path, "r", encoding="utf-8-sig")
    if True:')
    Expect 'break: open() without with -> red' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $true "open\(\) without 'with'"

    # 8e. Legitimate: a comment that mentions print( and open( stays green.
    $t = New-Tree 'm8e'
    $py = Join-Path $t 'skills\am-rhino-model-health\scripts\rhino_health.py'
    Add-Content -LiteralPath $py -Value '# Never print(json.dumps(x)) or f = open(p) here.'
    Expect 'legitimate: comment mentions print/open -> green' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $false 'Checked skill Python scripts: [1-9]'

    # 9. Legitimate: a full simulated split stays green for every check.
    $t = New-Tree 'split'
    $groups = @{
        core  = @('am-welcome', 'am-grilling', 'am-grill-me')
        rhino = @('am-rhino-setup')
    }
    $all = @(Get-ChildItem (Join-Path $t 'skills') -Directory | ForEach-Object Name)
    $groups.revit = @($all | Where-Object { $groups.core -notcontains $_ -and $groups.rhino -notcontains $_ })
    foreach ($g in $groups.Keys) {
        New-Item -ItemType Directory -Force (Join-Path $t "plugins\$g\skills") | Out-Null
        foreach ($s in $groups[$g]) { Move-Item (Join-Path $t "skills\$s") (Join-Path $t "plugins\$g\skills\$s") }
    }
    New-Item -ItemType Directory -Force (Join-Path $t 'plugins\core') | Out-Null
    Remove-Item -Recurse -Force (Join-Path $t 'skills')
    Move-Item (Join-Path $t 'hooks') (Join-Path $t 'plugins\core\hooks')
    foreach ($g in 'core', 'revit', 'rhino') {
        Set-Text (Join-Path $t "plugins\$g\.claude-plugin\plugin.json") ('{ "name": "archi-magic-' + $g + '" }')
        Add-MarketEntry $t "archi-magic-$g" "./plugins/$g"
    }
    # Shared copies follow the skill into its plugin.
    $sf = Join-Path $t 'scripts\lib\shared-files.ps1'
    Set-Text $sf (([IO.File]::ReadAllText($sf)) -replace "Copy = 'skills/am-bim-viewer/", "Copy = 'plugins/revit/skills/am-bim-viewer/")
    $dt = Join-Path $t 'scripts\lib\design-templates.ps1'
    Set-Text $dt (([IO.File]::ReadAllText($dt)) -replace "'skills/am-schedule-view/", "'plugins/revit/skills/am-schedule-view/" -replace "'skills/am-model-health/", "'plugins/revit/skills/am-model-health/")
    Expect 'legitimate: simulated split -> check-skills green' (Invoke-Check 'check-skills.ps1' $t @('-Root', $t)) $false 'Checked split plugin manifests: 3; rules hook in 1 hooks.json'
    Expect 'legitimate: simulated split -> check-version-bump green' (Invoke-Check 'check-version-bump.ps1' $t) $false '6 plugin manifest'
    Expect 'legitimate: simulated split -> sync-house-rules green' (Invoke-Check 'sync-house-rules.ps1' $t) $false 'unchanged'
} finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Base
}

Write-Host ("{0} case(s), {1} failed" -f $script:Cases, $script:Fail)
if ($script:Cases -eq 0) { Write-Host 'FAIL: no cases ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

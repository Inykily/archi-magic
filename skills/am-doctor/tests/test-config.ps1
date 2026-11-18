<#
.SYNOPSIS
  Tests for the am-doctor 'config' group (issue #253): Claude Code JSON files with a byte-order
  mark (BOM) or bad JSON, -Fix CONFIG_BOM, and personal skill copies that shadow a plugin skill.
  Hermetic: every case uses a throwaway CLAUDE_CONFIG_DIR, a temp backup root and a temp log
  folder. Never reads or writes the real ~/.claude files.

  Cases:
    1. known_marketplaces.json written the way the issue did it (Windows PowerShell 5.1
       'Set-Content -Encoding utf8', so with a UTF-8 BOM), found through CLAUDE_CONFIG_DIR only:
       CONFIG_BOM error, exit 1. With a BOM in installed_plugins.json too, the deps check
       (ReadAllText) still reads that file: the BOM is invisible to it, so only the byte check finds it.
    2. settings.json written with 'Out-File' (UTF-16 LE BOM): CONFIG_BOM names UTF-16 LE.
    3. installed_plugins.json not valid JSON, and an empty settings.json: CONFIG_BAD_JSON, and
       the evidence never quotes the file text.
    4. Clean files: CONFIG ok, exit 0.
    5. -Fix CONFIG_BOM: backup byte-identical to the old file, the new file equals the old bytes
       without the BOM (UTF-8) or the same JSON in UTF-8 (UTF-16), the doctor is then clean, and a
       second -Fix says "Nothing to fix".
    6. -Fix CONFIG_BOM on a BOM + broken JSON file: BOM removed, exit 1, names CONFIG_BAD_JSON.
    7. Personal skill copies: a copy of am-doctor (this plugin), a folder with the frontmatter
       name am-feedback, a copy of a skill from another installed plugin -> SKILL_SHADOW warn that
       names all three and not the own skill. No copies -> SKILLS ok.

  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-doctor\tests\test-config.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Doctor = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\doctor.ps1')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-doctor-config-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$NoBom = New-Object Text.UTF8Encoding $false
$script:Fail = 0; $script:Asserts = 0

function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name :`n$detail" }
}
function Get-Lines([string]$out, [string]$pattern) { @(($out -split "`r?`n") | Where-Object { $_ -match $pattern }) }
# A throwaway Claude config folder with three valid files and an archi-magic entry.
function New-Config([string]$name) {
    $cfg = Join-Path $Root $name
    New-Item -ItemType Directory -Force (Join-Path $cfg 'plugins') | Out-Null
    [IO.File]::WriteAllText((Join-Path $cfg 'plugins\known_marketplaces.json'), '{"archi-magic":{"source":{"source":"github","repo":"zsenarchitect/archi-magic"},"installLocation":"x","autoUpdate":true}}', $NoBom)
    [IO.File]::WriteAllText((Join-Path $cfg 'plugins\installed_plugins.json'), '{"version":2,"plugins":{"other@market":[{"scope":"user","installPath":"none","version":"1.0.0"}]}}', $NoBom)
    [IO.File]::WriteAllText((Join-Path $cfg 'settings.json'), '{"enabledPlugins":{}}', $NoBom)
    return $cfg
}
# Runs the doctor with CLAUDE_CONFIG_DIR = $cfg and no explicit Claude paths, so the defaults are tested.
function Invoke-Doctor([string]$cfg, [string[]]$extra = @()) {
    $env:CLAUDE_CONFIG_DIR = $cfg
    try {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Doctor -LogDir (Join-Path $Root 'logs') -DoctorBackupRoot (Join-Path $Root 'backups') @extra 2>&1 | Out-String
        return @{ Code = $LASTEXITCODE; Out = $out }
    } finally { Remove-Item Env:\CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue }
}
function Get-Bytes([string]$path) { , [IO.File]::ReadAllBytes($path) }
function Test-SameBytes([byte[]]$a, [byte[]]$b) {
    if ($a.Length -ne $b.Length) { return $false }
    for ($i = 0; $i -lt $a.Length; $i++) { if ($a[$i] -ne $b[$i]) { return $false } }
    return $true
}

try {
    New-Item -ItemType Directory -Force $Root | Out-Null
    $env:ARCHI_MAGIC_LOG_DIR = Join-Path $Root 'logs'   # keep test runs out of the real shared log

    # 1. The exact edit from the issue, in Windows PowerShell 5.1.
    $cfg = New-Config 'c1'
    $km = Join-Path $cfg 'plugins\known_marketplaces.json'
    $edit = "`$p = '$km'; `$j = [IO.File]::ReadAllText(`$p) | ConvertFrom-Json; `$j.'archi-magic'.autoUpdate = `$true; `$j | ConvertTo-Json -Depth 10 | Set-Content `$p -Encoding utf8"
    & powershell.exe -NoProfile -Command $edit
    $b = Get-Bytes $km
    Assert-True '1: setup - Set-Content -Encoding utf8 in PS 5.1 wrote a BOM' ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) "first bytes: $($b[0..2] -join ',')"
    # The same BOM in installed_plugins.json: the deps check reads it with ReadAllText, which skips it.
    $ip = Join-Path $cfg 'plugins\installed_plugins.json'
    [IO.File]::WriteAllText($ip, [IO.File]::ReadAllText($ip), (New-Object Text.UTF8Encoding $true))
    $r = Invoke-Doctor $cfg @('-Only', 'config,deps')
    $l = @(Get-Lines $r.Out '^CONFIG_BOM \| error \|.*known_marketplaces\.json')
    Assert-True '1: CONFIG_BOM error for known_marketplaces.json via CLAUDE_CONFIG_DIR, exit 1' ($r.Code -eq 1 -and $l.Count -eq 1 -and $l[0] -match 'known_marketplaces\.json starts with a UTF-8 byte-order mark' -and $l[0] -match 'c1\\plugins\\known_marketplaces') "exit $($r.Code)`n$($r.Out)"
    Assert-True '1: the fix column names -Fix CONFIG_BOM' ($l.Count -eq 1 -and $l[0] -match 'Fix CONFIG_BOM') $r.Out
    Assert-True '1: CONFIG_BOM error for installed_plugins.json too' ((Get-Lines $r.Out '^CONFIG_BOM \| error \|.*installed_plugins\.json').Count -eq 1) $r.Out
    Assert-True '1: the deps check reads past the BOM (why a byte check is needed)' ((Get-Lines $r.Out '^DEPS \| info \|.*not in installed_plugins\.json').Count -eq 1) $r.Out

    # 2. Out-File in PS 5.1 writes UTF-16 LE with a BOM.
    $cfg = New-Config 'c2'
    $st = Join-Path $cfg 'settings.json'
    & powershell.exe -NoProfile -Command "'{`"enabledPlugins`":{}}' | Out-File '$st'"
    $r = Invoke-Doctor $cfg @('-Only', 'config')
    Assert-True '2: UTF-16 LE settings.json -> CONFIG_BOM names UTF-16 LE' ($r.Code -eq 1 -and (Get-Lines $r.Out '^CONFIG_BOM \| error \|.*settings\.json starts with a UTF-16 LE byte-order mark').Count -eq 1) "exit $($r.Code)`n$($r.Out)"

    # 3. Not valid JSON, and an empty file. The secret-looking text must not show in the output.
    $cfg = New-Config 'c3'
    [IO.File]::WriteAllText((Join-Path $cfg 'plugins\installed_plugins.json'), '{"plugins": {"x": secret-value-123 }', $NoBom)
    [IO.File]::WriteAllText((Join-Path $cfg 'settings.json'), '   ', $NoBom)
    $r = Invoke-Doctor $cfg @('-Only', 'config')
    Assert-True '3: bad JSON -> CONFIG_BAD_JSON for installed_plugins.json' ((Get-Lines $r.Out '^CONFIG_BAD_JSON \| error \|.*installed_plugins\.json: not valid JSON').Count -eq 1) $r.Out
    Assert-True '3: empty file -> CONFIG_BAD_JSON for settings.json' ((Get-Lines $r.Out '^CONFIG_BAD_JSON \| error \|.*settings\.json: the file is empty').Count -eq 1) $r.Out
    Assert-True '3: exit 1 and the file text is not quoted' ($r.Code -eq 1 -and $r.Out -notmatch 'secret-value-123') "exit $($r.Code)`n$($r.Out)"
    $r = Invoke-Doctor $cfg @('-Fix', 'CONFIG_BAD_JSON')
    Assert-True '3: -Fix CONFIG_BAD_JSON -> exit 4, says not to edit plugins files by hand' ($r.Code -eq 4 -and $r.Out -match 'Do not edit files under ~/.claude/plugins by hand') "exit $($r.Code)`n$($r.Out)"

    # 4. Clean files.
    $cfg = New-Config 'c4'
    $r = Invoke-Doctor $cfg @('-Only', 'config', '-PersonalSkillsDir', (Join-Path $Root 'no-skills'))
    Assert-True '4: clean files -> CONFIG ok, exit 0' ($r.Code -eq 0 -and (Get-Lines $r.Out '^CONFIG \| ok \|.*known_marketplaces\.json, installed_plugins\.json, settings\.json').Count -eq 1) "exit $($r.Code)`n$($r.Out)"

    # 5. -Fix CONFIG_BOM: UTF-8 BOM in known_marketplaces.json, UTF-16 LE in settings.json.
    $cfg = New-Config 'c5'
    $km = Join-Path $cfg 'plugins\known_marketplaces.json'; $st = Join-Path $cfg 'settings.json'
    $kmText = '{"archi-magic":{"autoUpdate":true,"note":"caf' + [char]0xE9 + '"}}'
    [IO.File]::WriteAllText($km, $kmText, (New-Object Text.UTF8Encoding $true))
    [IO.File]::WriteAllText($st, '{"enabledPlugins":{"a@b":true}}', (New-Object Text.UnicodeEncoding($false, $true)))
    $kmBefore = Get-Bytes $km; $stBefore = Get-Bytes $st
    $r = Invoke-Doctor $cfg @('-Fix', 'CONFIG_BOM')
    Assert-True '5: -Fix CONFIG_BOM exit 0' ($r.Code -eq 0) "exit $($r.Code)`n$($r.Out)"
    $kmAfter = Get-Bytes $km
    Assert-True '5: known_marketplaces.json = old bytes without the 3 BOM bytes' (Test-SameBytes $kmAfter ($kmBefore[3..($kmBefore.Length - 1)])) "after: $($kmAfter.Length) bytes, before: $($kmBefore.Length)"
    $stAfter = Get-Bytes $st
    Assert-True '5: settings.json = the same JSON as UTF-8 without a BOM' (Test-SameBytes $stAfter ($NoBom.GetBytes('{"enabledPlugins":{"a@b":true}}'))) ([Text.Encoding]::UTF8.GetString($stAfter))
    $bdirs = @(Get-ChildItem (Join-Path $Root 'backups') -Directory -ErrorAction SilentlyContinue)
    $bk = if ($bdirs.Count -eq 1) { Join-Path $bdirs[0].FullName 'known_marketplaces.json' } else { '' }
    $bs = if ($bdirs.Count -eq 1) { Join-Path $bdirs[0].FullName 'settings.json' } else { '' }
    Assert-True '5: one backup folder, both backups byte-identical to the old files' ($bdirs.Count -eq 1 -and (Test-Path -LiteralPath $bk) -and (Test-Path -LiteralPath $bs) -and (Test-SameBytes (Get-Bytes $bk) $kmBefore) -and (Test-SameBytes (Get-Bytes $bs) $stBefore)) "backup folders: $($bdirs.Count)`n$($r.Out)"
    $r = Invoke-Doctor $cfg @('-Only', 'config', '-PersonalSkillsDir', (Join-Path $Root 'no-skills'))
    Assert-True '5: after the fix the doctor is clean' ($r.Code -eq 0 -and (Get-Lines $r.Out '^CONFIG_').Count -eq 0) "exit $($r.Code)`n$($r.Out)"
    $r = Invoke-Doctor $cfg @('-Fix', 'CONFIG_BOM')
    Assert-True '5: a second -Fix CONFIG_BOM -> Nothing to fix, exit 0' ($r.Code -eq 0 -and $r.Out -match 'Nothing to fix') "exit $($r.Code)`n$($r.Out)"

    # 6. BOM + broken JSON: the BOM goes, the bad JSON stays a finding.
    $cfg = New-Config 'c6'
    $ip = Join-Path $cfg 'plugins\installed_plugins.json'
    [IO.File]::WriteAllText($ip, '{"plugins": ', (New-Object Text.UTF8Encoding $true))
    $r = Invoke-Doctor $cfg @('-Fix', 'CONFIG_BOM')
    $b = Get-Bytes $ip
    Assert-True '6: BOM + bad JSON -> BOM removed, exit 1, names CONFIG_BAD_JSON' ($r.Code -eq 1 -and $b[0] -ne 0xEF -and $r.Out -match 'CONFIG_BAD_JSON') "exit $($r.Code)`n$($r.Out)"

    # 7. Personal skill copies.
    $cfg = New-Config 'c7'
    $other = Join-Path $Root 'cache\other-plugin'
    New-Item -ItemType Directory -Force (Join-Path $other 'skills\other-skill'), (Join-Path $other '.claude-plugin') | Out-Null
    [IO.File]::WriteAllText((Join-Path $other 'skills\other-skill\SKILL.md'), "---`nname: other-skill`ndescription: x`n---`n", $NoBom)
    $inst = @{ version = 2; plugins = @{ 'other-plugin@market' = @(@{ scope = 'user'; installPath = $other; version = '1.0.0' }) } }
    [IO.File]::WriteAllText((Join-Path $cfg 'plugins\installed_plugins.json'), ($inst | ConvertTo-Json -Depth 6), $NoBom)
    $sk = Join-Path $cfg 'skills'
    foreach ($d in 'am-doctor', 'feedback-copy', 'other-skill', 'my-own-skill') { New-Item -ItemType Directory -Force (Join-Path $sk $d) | Out-Null }
    [IO.File]::WriteAllText((Join-Path $sk 'am-doctor\SKILL.md'), "---`nname: am-doctor`ndescription: old copy`n---`n", $NoBom)
    [IO.File]::WriteAllText((Join-Path $sk 'feedback-copy\SKILL.md'), "---`r`nname: am-feedback`r`ndescription: old copy`r`n---`r`n", $NoBom)
    [IO.File]::WriteAllText((Join-Path $sk 'other-skill\SKILL.md'), "---`nname: other-skill`ndescription: copy`n---`n", $NoBom)
    [IO.File]::WriteAllText((Join-Path $sk 'my-own-skill\SKILL.md'), "---`nname: my-own-skill`ndescription: mine`n---`n", $NoBom)
    $r = Invoke-Doctor $cfg @('-Only', 'config')
    $l = @(Get-Lines $r.Out '^SKILL_SHADOW \| warn \|')
    Assert-True '7: SKILL_SHADOW warn names am-doctor, am-feedback and other-skill, exit 1' ($r.Code -eq 1 -and $l.Count -eq 1 -and $l[0] -match '3 personal skill copies' -and $l[0] -match 'am-doctor \(archi-magic\)' -and $l[0] -match 'am-feedback \(archi-magic\)' -and $l[0] -match 'other-skill \(other-plugin@market\)') "exit $($r.Code)`n$($r.Out)"
    Assert-True '7: the own skill is not named' ($l.Count -eq 1 -and $l[0] -notmatch 'my-own-skill') $r.Out
    Remove-Item -Recurse -Force (Join-Path $sk 'am-doctor'), (Join-Path $sk 'feedback-copy'), (Join-Path $sk 'other-skill')
    $r = Invoke-Doctor $cfg @('-Only', 'config')
    Assert-True '7: only own skills -> SKILLS ok, exit 0' ($r.Code -eq 0 -and (Get-Lines $r.Out '^SKILLS \| ok \|').Count -eq 1) "exit $($r.Code)`n$($r.Out)"
} finally {
    Remove-Item Env:\CLAUDE_CONFIG_DIR, Env:\ARCHI_MAGIC_LOG_DIR -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host ("{0} assertion(s), {1} failure(s)" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL: no assertions ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

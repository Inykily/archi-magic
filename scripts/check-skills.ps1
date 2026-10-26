<#
.SYNOPSIS
  Drift guard for the archi-magic plugin(s). Skill folders are read from skills/ (today) and
  plugins/*/skills/ (after the planned split, docs/plans/2026-10-24-plugin-split.md). Fails (exit 1) when:
    - no skill folder is found at all
    - a folder under skills/ does not start with "am-"
    - a skill folder has no SKILL.md
    - the SKILL.md frontmatter "name" is not the folder name
    - the SKILL.md frontmatter has no "description"
    - two skills' descriptions share a quoted trigger phrase ("...", case-insensitive)
    - the root README.md does not mention the skill as `am-<name>`
    - the house rules at the end of a SKILL.md differ from HOUSE-RULES.md
    - hooks/hooks.json has no SessionStart command hook that reads hooks/session-rules.md
    - hooks/session-rules.md is missing, empty, not ASCII, or longer than 12 lines
    - more than one hooks.json (root or plugins/*) runs the rules hook (it must appear once per session)
    - a skill file names a skill with the old namespace "archi-magic:am-" (it breaks when a skill moves plugin)
    - a plugins/*/.claude-plugin/plugin.json "name" differs from its marketplace.json entry name
    - plugins/*/skills exists and a root skills/ folder still exists (the meta plugin must ship no skills)
    - a shared-file copy (scripts/lib/shared-files.ps1) differs from its source
    - a Rhino skill script does not print its result as one RESULT_PREFIX ("AM_RESULT ") line
    - a skill script calls open() outside a "with" statement
  Runs on Windows PowerShell 5.1 and PowerShell 7 (GitHub Actions ubuntu: pwsh).

.EXAMPLE
  pwsh -File scripts/check-skills.ps1
#>
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'

$problems = New-Object System.Collections.Generic.List[string]
$readme = [IO.File]::ReadAllText((Join-Path $Root 'README.md'))
# HOUSE-RULES.md is the single source; every SKILL.md must end with an identical copy.
$houseRules = ([IO.File]::ReadAllText((Join-Path $Root 'HOUSE-RULES.md')) -replace "`r`n", "`n").Trim()
$rootSkills = Join-Path $Root 'skills'
$splitSkillRoots = @(Get-ChildItem (Join-Path $Root 'plugins\*\skills') -Directory -ErrorAction SilentlyContinue)
$dirs = @(@(Get-ChildItem $rootSkills -Directory -ErrorAction SilentlyContinue) +
          @($splitSkillRoots | ForEach-Object { Get-ChildItem $_.FullName -Directory }) | Sort-Object Name)
if ($dirs.Count -eq 0) { Write-Host 'FAIL: no skill folders found under skills/ or plugins/*/skills/'; exit 1 }
if ($splitSkillRoots.Count -gt 0 -and (Test-Path -LiteralPath $rootSkills)) {
    $problems.Add('plugins/*/skills exists, so the root skills/ folder must be gone (the meta plugin at ./ must ship no skills)')
}
$triggerOwners = @{}

foreach ($d in $dirs) {
    $n = $d.Name
    if (-not $n.StartsWith('am-')) { $problems.Add("$n : folder name must start with 'am-'") }
    $md = Join-Path $d.FullName 'SKILL.md'
    if (-not (Test-Path $md)) { $problems.Add("$n : SKILL.md is missing"); continue }

    $text = [IO.File]::ReadAllText($md)
    $fm = [regex]::Match($text, '\A---\r?\n(.*?)\r?\n---', 'Singleline')
    if (-not $fm.Success) { $problems.Add("$n : SKILL.md has no frontmatter block"); continue }
    $name = [regex]::Match($fm.Groups[1].Value, '(?m)^name:\s*(.+?)\s*$').Groups[1].Value
    $desc = [regex]::Match($fm.Groups[1].Value, '(?m)^description:\s*(.+?)\s*$').Groups[1].Value
    if ($name -ne $n) { $problems.Add("$n : frontmatter name is '$name', expected '$n'") }
    if (-not $desc) { $problems.Add("$n : frontmatter has no description") }
    # Trigger phrases: every "..." string in the description. Two skills must not share one,
    # or Claude cannot tell which skill the user means. No exemptions: am-grill-me is
    # user-only (disable-model-invocation) and its description has no quoted phrases.
    foreach ($m in [regex]::Matches($desc, '"([^"]+)"')) {
        $p = ($m.Groups[1].Value.Trim().ToLowerInvariant() -replace '\s+', ' ')
        if (-not $triggerOwners.ContainsKey($p)) { $triggerOwners[$p] = New-Object System.Collections.Generic.List[string] }
        if (-not $triggerOwners[$p].Contains($n)) { $triggerOwners[$p].Add($n) }
    }
    if (-not $readme.Contains("``$n``")) { $problems.Add("$n : README.md skills table does not mention ``$n``") }
    if (-not ($text -replace "`r`n", "`n").TrimEnd().EndsWith($houseRules)) {
        $problems.Add("$n : house rules differ from HOUSE-RULES.md (run scripts/sync-house-rules.ps1)")
    }
    # The old namespaced form breaks when a skill moves to another plugin; use the bare skill name.
    foreach ($f in @(Get-ChildItem $d.FullName -Recurse -File -Include *.md, *.ps1, *.py, *.mjs, *.js, *.json -ErrorAction SilentlyContinue |
                     Where-Object { $_.FullName -notmatch '[\\/]node_modules[\\/]' })) {
        if ([IO.File]::ReadAllText($f.FullName).Contains('archi-magic:am-')) {
            $problems.Add("$n : $($f.Name) names a skill as 'archi-magic:am-...'; use the bare name (am-...)")
        }
    }
}
$dupTriggers = 0
foreach ($p in ($triggerOwners.Keys | Sort-Object)) {
    if ($triggerOwners[$p].Count -gt 1) {
        $problems.Add(("duplicate trigger phrase ""{0}"" in: {1}" -f $p, ($triggerOwners[$p] -join ', ')))
        $dupTriggers++
    }
}

# SessionStart rules hook: hooks/hooks.json must run it, and hooks/session-rules.md must stay a
# short ASCII block (it is added to every session, and PS 5.1 writes stdout in the OEM code page).
# The hooks live in hooks/ today and in plugins/core/hooks/ after the split. Exactly one hooks.json
# may run the rules hook, or the rules block is added twice to every session.
$hookFiles = @(@(Join-Path $Root 'hooks/hooks.json') + @(Get-ChildItem (Join-Path $Root 'plugins\*\hooks\hooks.json') -ErrorAction SilentlyContinue | ForEach-Object FullName) |
               Where-Object { Test-Path -LiteralPath $_ })
$rulesOwners = @()
foreach ($hf in $hookFiles) {
    try {
        $hj = [IO.File]::ReadAllText($hf) | ConvertFrom-Json
        $ss = @($hj.hooks.SessionStart | ForEach-Object { $_.hooks } | Where-Object { $_.type -eq 'command' })
        if (@($ss | Where-Object { ((@($_.command) + @($_.args)) -join ' ') -match 'session-rules\.md' }).Count -gt 0) { $rulesOwners += $hf }
    } catch {
        $problems.Add("$hf is not valid JSON: $($_.Exception.Message)")
    }
}
if ($rulesOwners.Count -eq 0) { $problems.Add('no hooks.json (hooks/ or plugins/*/hooks/) has a SessionStart command hook that reads session-rules.md') }
if ($rulesOwners.Count -gt 1) { $problems.Add("the rules hook is in $($rulesOwners.Count) hooks.json files ($($rulesOwners -join ', ')); it must be in exactly one") }
$rulesMd = if ($rulesOwners.Count -ge 1) { Join-Path (Split-Path -Parent $rulesOwners[0]) 'session-rules.md' } else { Join-Path $Root 'hooks/session-rules.md' }
$maxRuleLines = 12
if (-not (Test-Path -LiteralPath $rulesMd)) {
    $problems.Add('hooks/session-rules.md is missing')
} else {
    $ruleBytes = [IO.File]::ReadAllBytes($rulesMd)
    if (@($ruleBytes | Where-Object { $_ -gt 127 }).Count -gt 0) { $problems.Add('hooks/session-rules.md must be ASCII only') }
    $ruleLines = @(([Text.Encoding]::ASCII.GetString($ruleBytes) -replace "`r`n", "`n").Trim() -split "`n")
    if ($ruleLines.Count -gt $maxRuleLines) { $problems.Add("hooks/session-rules.md has $($ruleLines.Count) lines; max is $maxRuleLines") }
    if (($ruleLines -join '').Trim().Length -eq 0) { $problems.Add('hooks/session-rules.md is empty') }
}

# Design tokens: every page template carries an identical copy of design/tokens.css.
$tokensPath = Join-Path $Root 'design/tokens.css'
$designOk = 0
if (Test-Path -LiteralPath $tokensPath) {
    $tokens = ([IO.File]::ReadAllText($tokensPath) -replace "`r`n", "`n").Trim()
    . (Join-Path $Root 'scripts/lib/design-templates.ps1')
    $tokRx = [regex]'(?s)/\* am-tokens:start.*?/\* am-tokens:end \*/'
    $themeRx = [regex]'(?s)// am-theme:start.*?// am-theme:end'
    $theme = ([IO.File]::ReadAllText((Join-Path $Root 'design/theme.js')) -replace "`r`n", "`n").Trim()
    foreach ($rel in $AmDesignTemplates) {
        $p = Join-Path $Root $rel
        if (-not (Test-Path -LiteralPath $p)) { $problems.Add("$rel : page template is missing (listed in scripts/lib/design-templates.ps1)"); continue }
        $pageText = [IO.File]::ReadAllText($p) -replace "`r`n", "`n"
        $tm = $themeRx.Match($pageText)
        if (-not $tm.Success) { $problems.Add("$rel : no time-of-day theme block (am-theme markers); run scripts/sync-design-tokens.ps1 after adding it") }
        elseif ($tm.Value.Trim() -ne $theme) { $problems.Add("$rel : theme block differs from design/theme.js (run scripts/sync-design-tokens.ps1)") }
        $m = $tokRx.Match($pageText)
        if (-not $m.Success) { $problems.Add("$rel : no design tokens block (am-tokens markers); run scripts/sync-design-tokens.ps1 after adding it") }
        elseif ($m.Value.Trim() -ne $tokens) { $problems.Add("$rel : design tokens differ from design/tokens.css (run scripts/sync-design-tokens.ps1)") }
        else { $designOk++ }
    }
} else {
    $problems.Add('design/tokens.css is missing')
}

# Shared files (S1): each copy must equal its source (line endings normalized), or an installed
# plugin runs stale code. Edit the source, then run scripts/sync-shared-files.ps1.
$sharedOk = 0
. (Join-Path $Root 'scripts/lib/shared-files.ps1')
if (@($AmSharedFiles).Count -eq 0) { $problems.Add('scripts/lib/shared-files.ps1 lists no files') }
foreach ($f in $AmSharedFiles) {
    $src = Join-Path $Root $f.Source; $dst = Join-Path $Root $f.Copy
    if (-not (Test-Path -LiteralPath $src)) { $problems.Add("$($f.Source) : shared-file source is missing"); continue }
    if (-not (Test-Path -LiteralPath $dst)) { $problems.Add("$($f.Copy) : shared-file copy is missing (run scripts/sync-shared-files.ps1)"); continue }
    $a = [IO.File]::ReadAllText($src) -replace "`r`n", "`n"; $b = [IO.File]::ReadAllText($dst) -replace "`r`n", "`n"
    if ($a -ne $b) { $problems.Add("$($f.Copy) : differs from $($f.Source) (run scripts/sync-shared-files.ps1)") } else { $sharedOk++ }
}

# Split plugins (A6): each plugins/<x>/.claude-plugin/plugin.json "name" must equal the name of the
# marketplace.json entry whose source is ./plugins/<x>. Skills are namespaced under the manifest
# name, and enabledPlugins uses the entry name; a mismatch breaks both.
$market = [IO.File]::ReadAllText((Join-Path $Root '.claude-plugin/marketplace.json')) | ConvertFrom-Json
$splitManifests = @(Get-ChildItem (Join-Path $Root 'plugins\*\.claude-plugin\plugin.json') -ErrorAction SilentlyContinue)
foreach ($pm in $splitManifests) {
    $folder = $pm.Directory.Parent.Name
    $man = [IO.File]::ReadAllText($pm.FullName) | ConvertFrom-Json
    $entry = @($market.plugins | Where-Object { $_.source -is [string] -and ($_.source.TrimEnd('/') -eq "./plugins/$folder") }) | Select-Object -First 1
    if (-not $entry) { $problems.Add("plugins/$folder : no marketplace.json entry with source ./plugins/$folder") }
    elseif ($entry.name -ne $man.name) { $problems.Add("plugins/$folder : plugin.json name '$($man.name)' differs from marketplace entry name '$($entry.name)'") }
}

# Skill Python scripts (2026-10-26 session lessons):
#  - A Rhino script (it reads __rhino_doc__) must print every result as one RESULT_PREFIX line.
#    Rhino writes its own lines ("Creating meshes...") to run_python stdout, so a bare JSON print
#    does not parse.
#  - A file open must use "with". Revit-hosted IronPython keeps an unclosed handle until GC, and
#    the locked file blocked "git pull" on the user's checkout.
$pyChecked = 0
foreach ($d in $dirs) {
    foreach ($py in @(Get-ChildItem (Join-Path $d.FullName 'scripts') -Filter *.py -File -ErrorAction SilentlyContinue)) {
        $pyChecked++
        $rel = "$($d.Name)/scripts/$($py.Name)"
        $lines = @([IO.File]::ReadAllLines($py.FullName) | Where-Object { $_ -notmatch '^\s*#' })
        if (@($lines | Where-Object { $_ -match '__rhino_doc__' }).Count -gt 0) {
            if (@($lines | Where-Object { $_ -match '^RESULT_PREFIX = "AM_RESULT "\s*$' }).Count -ne 1) {
                $problems.Add("$rel : Rhino script must define RESULT_PREFIX = `"AM_RESULT `" once")
            }
            foreach ($l in @($lines | Where-Object { $_ -match '(^|[^\w.])print\(' -and $_ -notmatch 'print\(RESULT_PREFIX \+' })) {
                $problems.Add("$rel : Rhino script prints without RESULT_PREFIX: $($l.Trim())")
            }
        }
        foreach ($l in @($lines | Where-Object { $_ -match '(^|[^\w.])((io|codecs)\.)?open\(' -and $_ -notmatch '^\s*with\s' })) {
            $problems.Add("$rel : open() without 'with' (an unclosed handle locks the file in Revit): $($l.Trim())")
        }
    }
}

Write-Host ("Checked {0} skill folder(s): {1}" -f $dirs.Count, (($dirs | ForEach-Object Name) -join ', '))
Write-Host ("Checked trigger phrases: {0} unique, {1} shared by two or more skills" -f $triggerOwners.Count, $dupTriggers)
Write-Host ("Checked design tokens: {0} page template(s) in sync" -f $designOk)
Write-Host ("Checked skill Python scripts: {0}" -f $pyChecked)
Write-Host ("Checked shared files: {0} of {1} copies in sync" -f $sharedOk, @($AmSharedFiles).Count)
Write-Host ("Checked split plugin manifests: {0}; rules hook in {1} hooks.json" -f $splitManifests.Count, $rulesOwners.Count)
Write-Host ("Checked SessionStart rules hook: {0}" -f $(if (Test-Path -LiteralPath $rulesMd) { "$(@(([IO.File]::ReadAllText($rulesMd) -replace "`r`n", "`n").Trim() -split "`n").Count) line(s)" } else { 'missing' }))
if ($problems.Count -gt 0) {
    Write-Host "FAIL: $($problems.Count) problem(s)"
    $problems | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host 'PASS'
exit 0

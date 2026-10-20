<#
.SYNOPSIS
  Drift guard for the archi-magic plugin. Fails (exit 1) when:
    - a folder under skills/ does not start with "am-"
    - a skill folder has no SKILL.md
    - the SKILL.md frontmatter "name" is not the folder name
    - the SKILL.md frontmatter has no "description"
    - the root README.md does not mention the skill as `am-<name>`
    - the house rules at the end of a SKILL.md differ from HOUSE-RULES.md
    - hooks/hooks.json has no SessionStart command hook that reads hooks/session-rules.md
    - hooks/session-rules.md is missing, empty, not ASCII, or longer than 12 lines
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
$dirs = @(Get-ChildItem (Join-Path $Root 'skills') -Directory | Sort-Object Name)
if ($dirs.Count -eq 0) { Write-Host 'FAIL: no skill folders found under skills/'; exit 1 }

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
    if (-not $readme.Contains("``$n``")) { $problems.Add("$n : README.md skills table does not mention ``$n``") }
    if (-not ($text -replace "`r`n", "`n").TrimEnd().EndsWith($houseRules)) {
        $problems.Add("$n : house rules differ from HOUSE-RULES.md (run scripts/sync-house-rules.ps1)")
    }
}

# SessionStart rules hook: hooks/hooks.json must run it, and hooks/session-rules.md must stay a
# short ASCII block (it is added to every session, and PS 5.1 writes stdout in the OEM code page).
$hooksJson = Join-Path $Root 'hooks/hooks.json'
$rulesMd   = Join-Path $Root 'hooks/session-rules.md'
$maxRuleLines = 12
if (-not (Test-Path -LiteralPath $hooksJson)) {
    $problems.Add('hooks/hooks.json is missing (SessionStart rules hook)')
} else {
    try {
        $hj = [IO.File]::ReadAllText($hooksJson) | ConvertFrom-Json
        $ss = @($hj.hooks.SessionStart | ForEach-Object { $_.hooks } | Where-Object { $_.type -eq 'command' })
        $refs = @($ss | Where-Object { ((@($_.command) + @($_.args)) -join ' ') -match 'session-rules\.md' })
        if ($refs.Count -eq 0) { $problems.Add('hooks/hooks.json has no SessionStart command hook that reads hooks/session-rules.md') }
    } catch {
        $problems.Add("hooks/hooks.json is not valid JSON: $($_.Exception.Message)")
    }
}
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

Write-Host ("Checked {0} skill folder(s): {1}" -f $dirs.Count, (($dirs | ForEach-Object Name) -join ', '))
Write-Host ("Checked design tokens: {0} page template(s) in sync" -f $designOk)
Write-Host ("Checked SessionStart rules hook: {0}" -f $(if (Test-Path -LiteralPath $rulesMd) { "$(@(([IO.File]::ReadAllText($rulesMd) -replace "`r`n", "`n").Trim() -split "`n").Count) line(s)" } else { 'missing' }))
if ($problems.Count -gt 0) {
    Write-Host "FAIL: $($problems.Count) problem(s)"
    $problems | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host 'PASS'
exit 0

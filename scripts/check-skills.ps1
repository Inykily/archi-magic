<#
.SYNOPSIS
  Drift guard for the archi-magic plugin. Fails (exit 1) when:
    - a folder under skills/ does not start with "am-"
    - a skill folder has no SKILL.md
    - the SKILL.md frontmatter "name" is not the folder name
    - the SKILL.md frontmatter has no "description"
    - the root README.md does not mention the skill as `am-<name>`
  Runs on Windows PowerShell 5.1 and PowerShell 7 (GitHub Actions ubuntu: pwsh).

.EXAMPLE
  pwsh -File scripts/check-skills.ps1
#>
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'

$problems = New-Object System.Collections.Generic.List[string]
$readme = [IO.File]::ReadAllText((Join-Path $Root 'README.md'))
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
}

Write-Host ("Checked {0} skill folder(s): {1}" -f $dirs.Count, (($dirs | ForEach-Object Name) -join ', '))
if ($problems.Count -gt 0) {
    Write-Host "FAIL: $($problems.Count) problem(s)"
    $problems | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host 'PASS'
exit 0

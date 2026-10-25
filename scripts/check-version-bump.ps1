<#
.SYNOPSIS
  archi-magic uses commit-derived versions: no plugin.json and no marketplace entry for a
  relative-path plugin may pin "version". Claude Code then uses the commit SHA as the version,
  so every merge to main reaches users as a new version automatically (auto-update on, or
  /plugin > Marketplaces > archi-magic > Update marketplace). A pinned "version" would freeze every user on the
  cached copy until someone changed the string. This check fails (exit 1) if one is pinned.
  Source: https://code.claude.com/docs/en/plugins/loading.md ("How Claude Code computes the version").

  External dependencies (url / git-subdir sources) are pinned by "sha" in marketplace.json instead;
  their version comes from that sha. That is checked weekly by scripts/check-upstream.ps1.

.EXAMPLE
  pwsh -File scripts/check-version-bump.ps1
#>
param([string]$Base = '')   # kept for the existing CI call; not needed any more
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

$problems = New-Object System.Collections.Generic.List[string]
$manifests = @('.claude-plugin/plugin.json') +
    @(Get-ChildItem 'mods/*/.claude-plugin/plugin.json' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }) +
    @(Get-ChildItem 'plugins/*/.claude-plugin/plugin.json' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
foreach ($m in $manifests) {
    $j = Get-Content -LiteralPath $m -Raw | ConvertFrom-Json
    if ($j.PSObject.Properties.Name -contains 'version') {
        $problems.Add("$m pins ""version"": ""$($j.version)"". Remove it; versions come from the commit.")
    }
}
$market = Get-Content -LiteralPath '.claude-plugin/marketplace.json' -Raw | ConvertFrom-Json
foreach ($p in $market.plugins) {
    if ($p.source -is [string] -and ($p.PSObject.Properties.Name -contains 'version')) {
        $problems.Add("marketplace.json entry '$($p.name)' pins ""version"". Remove it; versions come from the commit.")
    }
}

if ($problems.Count -gt 0) {
    Write-Host "FAIL: $($problems.Count) pinned version(s):"
    $problems | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host "PASS: no pinned versions ($($manifests.Count) plugin manifest(s)); every merge to main is a new version."
exit 0

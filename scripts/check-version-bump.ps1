<#
.SYNOPSIS
  Fails (exit 1) when plugin content changed since -Base but the version in
  .claude-plugin/plugin.json did not go up. Installed copies are cached by version,
  so unbumped content never reaches users.

  Plugin content = skills/**, .claude-plugin/**, scripts/** that ship with skills.
  Repo-only files (README.md, LICENSE, .github/**, scripts/check-*.ps1, .gitignore) do not need a bump.

.EXAMPLE
  pwsh -File scripts/check-version-bump.ps1 -Base origin/main
  pwsh -File scripts/check-version-bump.ps1 -Base <sha before the push>
#>
param([Parameter(Mandatory = $true)][string]$Base)
$ErrorActionPreference = 'Stop'

# git writes to stderr for an unknown base; with 'Stop', Windows PowerShell would turn that
# into a terminating error before the exit code can be read. Relax it for this one probe.
$ErrorActionPreference = 'Continue'
$null = git cat-file -e "$Base^{commit}" 2>&1
$baseOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = 'Stop'
if (-not $baseOk) {
    # First push of a branch or a force push: nothing reliable to compare against. Say so; do not pass silently.
    Write-Host "UNVERIFIED: base '$Base' is not a commit in this clone; version-bump check skipped."
    exit 0
}

$changed = @(git diff --name-only "$Base" HEAD)
$content = @($changed | Where-Object { $_ -match '^(skills/|\.claude-plugin/)' })
if ($content.Count -eq 0) {
    Write-Host "PASS: no plugin content changed since $Base ($($changed.Count) repo-only file(s) changed)."
    exit 0
}

function Get-Version([string]$json) {
    $m = [regex]::Match($json, '"version"\s*:\s*"(\d+\.\d+\.\d+)"')
    if ($m.Success) { return [version]$m.Groups[1].Value } else { return $null }
}
$before = Get-Version ((git show "${Base}:.claude-plugin/plugin.json" 2>$null) -join "`n")
$after  = Get-Version ([IO.File]::ReadAllText('.claude-plugin/plugin.json'))
if (-not $after) { Write-Host 'FAIL: .claude-plugin/plugin.json has no semver version.'; exit 1 }

Write-Host "Plugin content changed in $($content.Count) file(s):"
$content | ForEach-Object { Write-Host "  $_" }
if ($before -and $after -le $before) {
    Write-Host "FAIL: version is $after, was $before at $Base. Run scripts/bump-version.ps1 patch|minor|major."
    exit 1
}
Write-Host "PASS: version $before -> $after."
exit 0

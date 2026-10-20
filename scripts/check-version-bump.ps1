<#
.SYNOPSIS
  Fails (exit 1) when a changed file needs a version bump and the version did not go up.
  Installed copies are cached by version, so unbumped content never reaches users.

  Rule: EVERY changed path needs a bump of the root .claude-plugin/plugin.json version,
  EXCEPT these repo-only paths:
    README.md, LICENSE, docs/**, .github/**, .gitignore, .gitattributes,
    scripts/check-*.ps1, scripts/bump-version.ps1, scripts/sync-house-rules.ps1
  Not exempt (examples): skills/**, mods/**, hooks/**, .claude-plugin/**, scripts/lib/**,
  HOUSE-RULES.md (it ships inside every SKILL.md after sync).

  Each mod (mods/<name>/) is its own plugin with its own version. A change under
  mods/<name>/ also needs mods/<name>/.claude-plugin/plugin.json to go up.

  Unknown base (first push of a branch, force push): prints a GitHub Actions ::warning::
  and exits 0, because there is nothing reliable to compare against.

  Runs from any working directory: it moves to the repo root first.

.EXAMPLE
  pwsh -File scripts/check-version-bump.ps1 -Base origin/main
  pwsh -File scripts/check-version-bump.ps1 -Base <sha before the push>
#>
param([Parameter(Mandatory = $true)][string]$Base)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

# git writes to stderr for an unknown base; with 'Stop', Windows PowerShell would turn that
# into a terminating error before the exit code can be read. Relax it for this one probe.
$ErrorActionPreference = 'Continue'
$null = git cat-file -e "$Base^{commit}" 2>&1
$baseOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = 'Stop'
if (-not $baseOk) {
    Write-Host "::warning title=Version bump not checked::Base '$Base' is not a commit in this clone (first push or force push). The version-bump check was skipped."
    Write-Host "UNVERIFIED: base '$Base' is not a commit in this clone; version-bump check skipped."
    exit 0
}

$exempt = @(
    '^README\.md$', '^LICENSE$', '^docs/', '^\.github/', '^\.gitignore$', '^\.gitattributes$',
    '^scripts/check-[^/]*\.ps1$', '^scripts/bump-version\.ps1$', '^scripts/sync-house-rules\.ps1$'
)
function Test-Exempt([string]$p) {
    foreach ($rx in $exempt) { if ($p -match $rx) { return $true } }
    return $false
}

function Get-Version([string]$json) {
    $m = [regex]::Match($json, '"version"\s*:\s*"(\d+\.\d+\.\d+)"')
    if ($m.Success) { return [version]$m.Groups[1].Value } else { return $null }
}
function Get-BaseVersion([string]$path) {
    $ErrorActionPreference = 'Continue'
    $text = (git show "${Base}:$path" 2>$null) -join "`n"
    if ($LASTEXITCODE -ne 0) { return $null }
    return Get-Version $text
}

$changed = @(git diff --name-only "$Base" HEAD)
$content = @($changed | Where-Object { -not (Test-Exempt $_) })
if ($content.Count -eq 0) {
    Write-Host "PASS: only repo-only files changed since $Base ($($changed.Count) file(s))."
    exit 0
}

$fail = $false
Write-Host "Plugin content changed in $($content.Count) file(s):"
$content | ForEach-Object { Write-Host "  $_" }

# Root plugin version.
$before = Get-BaseVersion '.claude-plugin/plugin.json'
$after  = Get-Version ([IO.File]::ReadAllText((Join-Path (Get-Location) '.claude-plugin/plugin.json')))
if (-not $after) { Write-Host 'FAIL: .claude-plugin/plugin.json has no semver version.'; exit 1 }
if ($before -and $after -le $before) {
    Write-Host "FAIL: version is $after, was $before at $Base. Run scripts/bump-version.ps1 patch|minor|major."
    $fail = $true
} else {
    Write-Host "PASS: archi-magic version $before -> $after."
}

# Each changed mod needs its own version bump too.
$mods = @($content | Where-Object { $_ -match '^mods/([^/]+)/' } | ForEach-Object { ($_ -split '/')[1] } | Sort-Object -Unique)
foreach ($mod in $mods) {
    $rel = "mods/$mod/.claude-plugin/plugin.json"
    $abs = Join-Path (Get-Location) $rel
    if (-not (Test-Path -LiteralPath $abs)) { continue }   # mod deleted
    $mAfter  = Get-Version ([IO.File]::ReadAllText($abs))
    $mBefore = Get-BaseVersion $rel
    if (-not $mAfter) { Write-Host "FAIL: $rel has no semver version."; $fail = $true; continue }
    if ($mBefore -and $mAfter -le $mBefore) {
        Write-Host "FAIL: mod $mod changed but $rel is still $mAfter (was $mBefore at $Base). Raise its version."
        $fail = $true
    } else {
        Write-Host "PASS: mod $mod version $mBefore -> $mAfter."
    }
}

if ($fail) { exit 1 }
exit 0

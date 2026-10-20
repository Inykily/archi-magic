<#
.SYNOPSIS
  Weekly upkeep report for archi-magic. Prints a Markdown report:
    - drift checks (check-skills.ps1)
    - upstream staleness of every pinned marketplace dependency (url / git-subdir sources)
    - the latest pyRevit release (setup installs "latest", so this is an FYI)
  Exit 0 always for the report itself; the caller decides what to do with it.
  A check that could not run is reported as UNVERIFIED, never as "up to date".

.EXAMPLE
  pwsh -File scripts/check-upstream.ps1 > report.md
#>
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Continue'
Set-Location $Root
$lines = New-Object System.Collections.Generic.List[string]
$attention = 0

$lines.Add('## Drift checks')
$psExe = (Get-Process -Id $PID).Path   # the running PowerShell (pwsh on CI, powershell.exe on Windows)
$drift = (& $psExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'scripts/check-skills.ps1') 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -eq 0) { $lines.Add('- PASS: skill folders, names, README rows and house rules are in sync.') }
else { $attention++; $lines.Add('- **FAIL**:'); $lines.Add('```'); $lines.Add($drift); $lines.Add('```') }
$lines.Add('- Reminder: open `am-welcome` once and check that its example questions still match what the skills do.')

$lines.Add('')
$lines.Add('## Pinned dependencies')
$lines.Add('| Plugin | Pinned | Upstream now | Status |')
$lines.Add('|---|---|---|---|')
$market = Get-Content (Join-Path $Root '.claude-plugin/marketplace.json') -Raw | ConvertFrom-Json
foreach ($p in $market.plugins) {
    $s = $p.source
    if ($s -is [string]) { continue }   # local plugins (./ and ./mods/...) ship with this repo
    $m = [regex]::Match([string]$s.url, 'github\.com/([^/]+/[^/.]+)')
    if (-not $m.Success -or -not $s.sha) { $attention++; $lines.Add("| $($p.name) | ? | ? | UNVERIFIED: no GitHub url or sha |"); continue }
    $repo = $m.Groups[1].Value
    $pathArg = if ($s.path) { "&path=$($s.path)" } else { '' }
    $json = gh api "repos/$repo/commits?per_page=1$pathArg" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $json) { $attention++; $lines.Add("| $($p.name) | $($s.sha.Substring(0,7)) | ? | UNVERIFIED: GitHub API call failed |"); continue }
    $latest = ($json | ConvertFrom-Json)[0].sha
    $pinned = $s.sha
    if ($latest -eq $pinned) { $lines.Add("| $($p.name) | $($pinned.Substring(0,7)) | $($latest.Substring(0,7)) | up to date |") }
    else {
        # $latest is the newest commit that touched the plugin's path. If it is BEHIND the pin
        # (or identical), the pin already contains every change to that path: up to date.
        $c = gh api "repos/$repo/compare/$pinned...$latest" 2>$null | ConvertFrom-Json
        if (-not $c) { $attention++; $lines.Add("| $($p.name) | $($pinned.Substring(0,7)) | $($latest.Substring(0,7)) | UNVERIFIED: compare failed |") }
        elseif ($c.status -in 'behind', 'identical') { $lines.Add("| $($p.name) | $($pinned.Substring(0,7)) | $($latest.Substring(0,7)) | up to date (last change to this plugin is already in the pin) |") }
        else {
            $attention++
            $lines.Add("| $($p.name) | $($pinned.Substring(0,7)) | $($latest.Substring(0,7)) | **newer upstream** ($($c.status), $($c.ahead_by) commit(s) ahead). Review its changes (hooks, scripts) before bumping the sha. |")
        }
    }
}

$lines.Add('')
$lines.Add('## pyRevit')
$r = gh api repos/pyrevitlabs/pyRevit/releases/latest 2>$null | ConvertFrom-Json
$rel = if ($r) { "$($r.tag_name) ($($r.published_at))" } else { $null }
if ($rel) { $lines.Add("- Latest release: $rel. ``am-pyrevit7-setup`` installs the latest release with a signer check; test a new major version before users meet it.") }
else { $attention++; $lines.Add('- UNVERIFIED: could not read the latest pyRevit release.') }

$header = if ($attention -gt 0) { "**$attention item(s) need attention.**" } else { 'Nothing needs attention this week.' }
Write-Output ("# Weekly archi-magic check`n`n" + $header + "`n`n" + ($lines -join "`n"))

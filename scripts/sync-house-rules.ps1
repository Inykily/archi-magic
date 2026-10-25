<#
.SYNOPSIS
  Copy HOUSE-RULES.md (the single source) into every skills/*/SKILL.md, replacing the
  existing "## House rules (all am-* skills)" section or appending it if missing.
  The section must be the last section of each SKILL.md.

.EXAMPLE
  powershell -File scripts/sync-house-rules.ps1
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$utf8 = New-Object Text.UTF8Encoding $false
$block = ([IO.File]::ReadAllText((Join-Path $root 'HOUSE-RULES.md'), $utf8) -replace "`r`n", "`n").Trim()
$marker = '## House rules (all am-* skills)'
if (-not $block.StartsWith($marker)) { Write-Host "FAIL: HOUSE-RULES.md must start with '$marker'"; exit 1 }

# Flat layout (skills/) and split layout (plugins/*/skills/). Zero matches is a failure, not a pass:
# a wrong glob after a move must not report success while updating nothing.
$mds = @(Get-ChildItem (Join-Path $root 'skills\*\SKILL.md') -ErrorAction SilentlyContinue) +
       @(Get-ChildItem (Join-Path $root 'plugins\*\skills\*\SKILL.md') -ErrorAction SilentlyContinue)
if ($mds.Count -eq 0) { Write-Host 'FAIL: no SKILL.md found under skills/ or plugins/*/skills/'; exit 1 }
foreach ($md in $mds) {
    $text = [IO.File]::ReadAllText($md.FullName, $utf8) -replace "`r`n", "`n"
    $at = $text.IndexOf($marker)
    $head = if ($at -ge 0) { $text.Substring(0, $at).TrimEnd() } else { $text.TrimEnd() }
    $new = $head + "`n`n" + $block + "`n"
    if ($new -ne $text) {
        [IO.File]::WriteAllText($md.FullName, $new, $utf8)
        Write-Host "updated  $($md.Directory.Name)"
    } else {
        Write-Host "unchanged $($md.Directory.Name)"
    }
}

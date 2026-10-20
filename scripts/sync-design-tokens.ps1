<#
.SYNOPSIS
  Copy design/tokens.css (the single source of the "Visual Research" design tokens) into every
  page template, replacing the block between the "/* am-tokens:start" and "/* am-tokens:end */"
  markers. Also copies design/theme.js (time-of-day day/night switch) between the
  "// am-theme:start" and "// am-theme:end" markers. check-skills.ps1 fails if a template's copy drifts or a known template lacks the block.

.EXAMPLE
  powershell -File scripts/sync-design-tokens.ps1
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$utf8 = New-Object Text.UTF8Encoding $false
$src = ([IO.File]::ReadAllText((Join-Path $root 'design/tokens.css'), $utf8) -replace "`r`n", "`n").Trim()
if (-not ($src.StartsWith('/* am-tokens:start') -and $src.EndsWith('/* am-tokens:end */'))) {
    Write-Host 'FAIL: design/tokens.css must start with "/* am-tokens:start" and end with "/* am-tokens:end */"'; exit 1
}
. (Join-Path $PSScriptRoot 'lib/design-templates.ps1')   # defines $AmDesignTemplates
$rx = [regex]'(?s)/\* am-tokens:start.*?/\* am-tokens:end \*/'
$themeSrc = ([IO.File]::ReadAllText((Join-Path $root 'design/theme.js'), $utf8) -replace "`r`n", "`n").Trim()
$themeRx = [regex]'(?s)// am-theme:start.*?// am-theme:end'
foreach ($rel in $AmDesignTemplates) {
    $path = Join-Path $root $rel
    if (-not (Test-Path -LiteralPath $path)) { Write-Host "missing  $rel"; continue }
    $text = [IO.File]::ReadAllText($path, $utf8) -replace "`r`n", "`n"
    if (-not $rx.IsMatch($text)) { Write-Host "NO MARKERS $rel (add the tokens block inside its <style> first)"; continue }
    $new = $rx.Replace($text, [Text.RegularExpressions.MatchEvaluator]{ param($m) $src }, 1)
    if ($themeRx.IsMatch($new)) { $new = $themeRx.Replace($new, [Text.RegularExpressions.MatchEvaluator]{ param($m) $themeSrc }, 1) }
    else { Write-Host "NO THEME MARKERS $rel (add a <script> with the am-theme block in <head>)" }
    if ($new -ne $text) { [IO.File]::WriteAllText($path, $new, $utf8); Write-Host "updated   $rel" }
    else { Write-Host "unchanged $rel" }
}

<#
.SYNOPSIS
  Render the am-safe-change material-colors panel: one self-contained HTML page
  from a read_materials.py result.

.DESCRIPTION
  Reads the template ..\assets\material-colors-panel.html, puts the data in place of the
  /*__PANEL_DATA__*/null token, and writes -Out. The JSON is not changed: the page
  reads it as {materials, rendered}. The page has no server: the user tunes colors
  in the page, clicks "Copy changes for Revit", and pastes the JSON back in chat.
  Works on Windows PowerShell 5.1 and PowerShell 7.

.PARAMETER Json
  The read result saved from run_query (read_materials.py `result`).
.PARAMETER Out
  The HTML file to write.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File render-panel.ps1 -Json "D:\Proj\colors\read.json" -Out "D:\Proj\colors\panel.html"

  Exit codes: 0 written, 1 bad input, 2 template missing.
#>
param(
    [Parameter(Mandatory = $true)][string]$Json,
    [Parameter(Mandatory = $true)][string]$Out
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding $false
$token = '/*__PANEL_DATA__*/null'

$template = Join-Path (Split-Path -Parent $PSScriptRoot) 'assets\material-colors-panel.html'
if (-not (Test-Path -LiteralPath $template)) { Write-Host "FAIL: template not found: $template"; exit 2 }

if (-not (Test-Path -LiteralPath $Json)) { Write-Host "FAIL: -Json file not found: $Json"; exit 1 }
$current = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $Json).Path, $utf8).Trim()
if ($current.Length -gt 0 -and $current[0] -eq [char]0xFEFF) { $current = $current.Substring(1) }
if (-not ($current.StartsWith('{') -and $current.EndsWith('}') -and $current.Contains('"materials"'))) {
    Write-Host "FAIL: $Json is not a read_materials.py result (needs materials)."; exit 1
}

$rendered = (Get-Date).ToString('yyyy-MM-dd HH:mm')
$data = '{"rendered":"' + $rendered + '","current":' + $current + '}'
# Keep the data inside its <script> element even if a name contains "</script>".
$data = $data.Replace('</', '<\/')

$html = [IO.File]::ReadAllText($template, $utf8)
if (-not $html.Contains($token)) { Write-Host "FAIL: template has no data token $token"; exit 2 }
$html = $html.Replace($token, $data)

$outDir = Split-Path -Parent ([IO.Path]::GetFullPath($Out))
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
[IO.File]::WriteAllText([IO.Path]::GetFullPath($Out), $html, $utf8)
Write-Host ("OK: wrote {0}" -f $Out)
exit 0

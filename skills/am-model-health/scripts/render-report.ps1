<#
.SYNOPSIS
  Render the am-model-health dashboard: one self-contained HTML page from a run JSON
  and an optional folder of earlier snapshots (for the trend lines).

.DESCRIPTION
  Reads the template ..\assets\report.html, puts the data in place of the
  /*__REPORT_DATA__*/null token, and writes -Out. The JSON is not changed: the page
  reads it as {current, history[], rendered}. Snapshot files that are not
  am-model-health results are skipped with a WARN line (they are not silently dropped).
  Works on Windows PowerShell 5.1 and PowerShell 7.

.PARAMETER Json
  The run result saved from run_query (model_health.py `result`).
.PARAMETER History
  Folder with earlier snapshot *.json files. Optional. The -Json file may also be in it.
.PARAMETER Out
  The HTML file to write.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File render-report.ps1 -Json "D:\Proj\archi-magic-health\Tower\2026-10-19_1507.json" -History "D:\Proj\archi-magic-health\Tower" -Out "D:\Proj\archi-magic-health\Tower\report.html"

  Exit codes: 0 written, 1 bad input, 2 template missing.
#>
param(
    [Parameter(Mandatory = $true)][string]$Json,
    [string]$History = '',
    [Parameter(Mandatory = $true)][string]$Out
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding $false
$token = '/*__REPORT_DATA__*/null'

$template = Join-Path (Split-Path -Parent $PSScriptRoot) 'assets\report.html'
if (-not (Test-Path -LiteralPath $template)) { Write-Host "FAIL: template not found: $template"; exit 2 }

function Read-Snapshot([string]$path) {
    # Light check only: PowerShell 5.1 ConvertFrom-Json is slow and size-limited on big files.
    $text = [IO.File]::ReadAllText($path, $utf8).Trim()
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
    if (-not ($text.StartsWith('{') -and $text.EndsWith('}') -and $text.Contains('"metrics"') -and $text.Contains('"timestamp"'))) {
        return $null
    }
    return $text
}

if (-not (Test-Path -LiteralPath $Json)) { Write-Host "FAIL: -Json file not found: $Json"; exit 1 }
$current = Read-Snapshot (Resolve-Path -LiteralPath $Json).Path
if ($null -eq $current) { Write-Host "FAIL: $Json is not an am-model-health result (needs metrics and timestamp)."; exit 1 }

$hist = New-Object System.Collections.Generic.List[string]
$skipped = 0
if ($History) {
    if (-not (Test-Path -LiteralPath $History -PathType Container)) {
        Write-Host "WARN: history folder not found, rendering without trend: $History"
    } else {
        $currentFull = (Resolve-Path -LiteralPath $Json).Path
        foreach ($f in Get-ChildItem -LiteralPath $History -Filter '*.json' | Sort-Object Name) {
            if ($f.FullName -eq $currentFull) { continue }
            $snap = Read-Snapshot $f.FullName
            if ($null -eq $snap) { Write-Host "WARN: skipped (not a health snapshot): $($f.Name)"; $skipped++; continue }
            $hist.Add($snap)
        }
    }
}

$rendered = (Get-Date).ToString('yyyy-MM-dd HH:mm')
$data = '{"rendered":"' + $rendered + '","current":' + $current + ',"history":[' + ($hist -join ',') + ']}'
# Keep the data inside its <script> element even if a name contains "</script>".
$data = $data.Replace('</', '<\/')

$html = [IO.File]::ReadAllText($template, $utf8)
if (-not $html.Contains($token)) { Write-Host "FAIL: template has no data token $token"; exit 2 }
$html = $html.Replace($token, $data)

$outDir = Split-Path -Parent ([IO.Path]::GetFullPath($Out))
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
[IO.File]::WriteAllText([IO.Path]::GetFullPath($Out), $html, $utf8)
Write-Host ("OK: wrote {0} (1 current + {1} history snapshot(s), {2} skipped)" -f $Out, $hist.Count, $skipped)
exit 0

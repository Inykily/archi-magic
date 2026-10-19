<#
.SYNOPSIS
  Full-text search of the official pyRevit docs (docs.pyrevitlabs.io) using the site's own
  search index, cached locally for 7 days.

.EXAMPLE
  .\search-pyrevit-docs.ps1 -Query "output window table"
  .\search-pyrevit-docs.ps1 -Query "agent policy" -Top 5
  .\search-pyrevit-docs.ps1 -Index            # print llms.txt: one line per docs page
  .\search-pyrevit-docs.ps1 -Query "forms" -Refresh

  Exit codes: 0 found, 1 nothing matched, 2 docs index unavailable.
#>
[CmdletBinding()]
param(
    [string]$Query = '',
    [int]$Top = 8,
    [switch]$Index,
    [switch]$Refresh
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Base = 'https://docs.pyrevitlabs.io/'
$CacheDir = Join-Path $env:LOCALAPPDATA 'archi-magic\cache'
New-Item -ItemType Directory -Force $CacheDir | Out-Null

function Get-Cached([string]$url, [string]$file) {
    $path = Join-Path $CacheDir $file
    $fresh = (Test-Path $path) -and ((Get-Date) - (Get-Item $path).LastWriteTime).TotalDays -lt 7
    if ($Refresh -or -not $fresh) {
        try {
            Invoke-WebRequest $url -OutFile "$path.tmp" -UseBasicParsing -TimeoutSec 60
            Move-Item "$path.tmp" $path -Force
        } catch {
            if (Test-Path $path) {
                Write-Host "WARNING: could not refresh $url ($($_.Exception.Message)). Using cached copy from $((Get-Item $path).LastWriteTime)."
            } else {
                Write-Host "Docs index unavailable: $url ($($_.Exception.Message)) and no cached copy."
                exit 2
            }
        }
    }
    return $path
}

if ($Index) {
    Get-Content (Get-Cached ($Base + 'llms.txt') 'pyrevit-llms.txt')
    exit 0
}
if (-not $Query) { Write-Host 'Give -Query "words" or -Index.'; exit 1 }

$si = [IO.File]::ReadAllText((Get-Cached ($Base + 'search/search_index.json') 'pyrevit-search_index.json')) | ConvertFrom-Json
$tokens = @($Query.ToLowerInvariant() -split '\s+' | Where-Object { $_ })

$hits = foreach ($d in $si.docs) {
    $title = [string]$d.title; $text = [string]$d.text
    $tl = $title.ToLowerInvariant(); $xl = $text.ToLowerInvariant()
    $score = 0; $ok = $true
    foreach ($t in $tokens) {
        $inTitle = $tl.Contains($t); $inText = $xl.Contains($t)
        if (-not ($inTitle -or $inText)) { $ok = $false; break }
        if ($inTitle) { $score += 10 }
        if ($inText) { $score += [Math]::Min(5, ([regex]::Matches($xl, [regex]::Escape($t))).Count) }
    }
    if ($ok) { [pscustomobject]@{ Score = $score; Doc = $d } }
}
$hits = @($hits | Sort-Object Score -Descending)
if ($hits.Count -eq 0) {
    Write-Host "No pyRevit docs section contains all of: $($tokens -join ', '). ($($si.docs.Count) sections searched.)"
    Write-Host 'Try fewer or different words, -Index to browse pages, or search the source: %APPDATA%\pyRevit-Master\pyrevitlib'
    exit 1
}

Write-Host "pyRevit docs: $($hits.Count) section(s) match '$Query'. Showing $([Math]::Min($Top, $hits.Count))."
foreach ($h in ($hits | Select-Object -First $Top)) {
    $d = $h.Doc
    $plain = ([string]$d.text -replace '<[^>]+>', ' ' -replace '\s+', ' ').Trim()
    $at = $plain.ToLowerInvariant().IndexOf($tokens[0])
    $start = [Math]::Max(0, $at - 120)
    $snip = if ($plain.Length -gt 0) { $plain.Substring($start, [Math]::Min(320, $plain.Length - $start)) } else { '' }
    Write-Host ''
    $title = ([string]$d.title -replace '<[^>]+>', '' -replace '\s+', ' ').Trim()
    Write-Host ("{0}  ->  {1}{2}" -f $title, $Base, $d.location)
    if ($snip) { Write-Host "  ...$snip..." }
}
exit 0

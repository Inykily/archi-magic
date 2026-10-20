<#
.SYNOPSIS
  Look up Revit API types and members in the RevitAPI.xml / RevitAPIUI.xml docs that
  ship with each installed Revit version. Offline and version-exact.

.EXAMPLE
  .\search-revit-api.ps1 -Query "Wall.Create"
  .\search-revit-api.ps1 -Query "FilteredElementCollector OfCategory" -Year 2024
  .\search-revit-api.ps1 -Query "ElementId.IntegerValue" -AllYears   # which installed years have it

  Exit codes: 0 found, 1 nothing matched, 2 no Revit API docs found on this machine.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Query,
    [int]$Year = 0,
    [int]$Top = 10,
    [ValidateSet('', 'T', 'M', 'P', 'F', 'E')][string]$Kind = '',
    [switch]$AllYears
)
$ErrorActionPreference = 'Stop'

$installed = @(Get-ChildItem 'C:\Program Files\Autodesk\Revit 20*\RevitAPI.xml' -ErrorAction SilentlyContinue |
    ForEach-Object { [int]($_.Directory.Name -replace '\D', '') } | Sort-Object -Descending)
if ($installed.Count -eq 0) {
    Write-Host 'No RevitAPI.xml found under C:\Program Files\Autodesk\Revit 20*. Revit is not installed here.'
    Write-Host 'Fall back to the online docs: https://www.revitapidocs.com/<year>/'
    exit 2
}
if ($Year -eq 0) { $Year = $installed[0] }
if ($installed -notcontains $Year) {
    Write-Host "Revit $Year is not installed. Installed: $($installed -join ', '). Use -Year with one of those, or https://www.revitapidocs.com/$Year/"
    exit 2
}

$kindNames = @{ T = 'Type'; M = 'Method'; P = 'Property'; F = 'Field/Enum value'; E = 'Event' }
$tokens = @($Query -split '[\s\.]+' | Where-Object { $_ } | ForEach-Object { $_.ToLowerInvariant() })

function Get-Members([int]$y) {
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($f in 'RevitAPI.xml', 'RevitAPIUI.xml') {
        $p = "C:\Program Files\Autodesk\Revit $y\$f"
        if (-not (Test-Path $p)) { continue }
        $x = New-Object Xml.XmlDocument
        $x.Load($p)
        foreach ($m in $x.doc.members.member) { $list.Add($m) }
    }
    return $list
}

function Find-Matches($members) {
    $hits = foreach ($m in $members) {
        $id = $m.name
        if ($Kind -and -not $id.StartsWith("$Kind`:")) { continue }
        $bare = ($id.Substring(2) -replace '\(.*$', '')
        $lower = $bare.ToLowerInvariant()
        $ok = $true
        foreach ($t in $tokens) { if (-not $lower.Contains($t)) { $ok = $false; break } }
        if (-not $ok) { continue }
        # Rank: name ends with the query (e.g. "...Wall.Create") > short names > the rest.
        $q = ($tokens -join '.')
        $score = 0
        if ($lower.EndsWith('.' + $q) -or $lower -eq $q) { $score += 100 }
        if ($lower.EndsWith('.' + $tokens[-1])) { $score += 20 }
        $score -= [Math]::Min(50, $bare.Length / 4)
        [pscustomobject]@{ Score = $score; Id = $id; Node = $m }
    }
    return @($hits | Sort-Object Score -Descending)
}

function Clean([string]$s) { return (($s -replace '\s+', ' ').Trim()) }

if ($AllYears) {
    foreach ($y in $installed) {
        $n = @(Find-Matches (Get-Members $y)).Count
        Write-Host ("Revit {0}: {1} matching member(s)" -f $y, $n)
    }
    exit 0
}

$members = Get-Members $Year
$hits = @(Find-Matches $members)
if ($hits.Count -eq 0) {
    Write-Host "No member matching '$Query' in Revit $Year RevitAPI.xml + RevitAPIUI.xml ($($members.Count) members searched)."
    Write-Host "Not found here does not mean it does not exist: try a shorter query, -AllYears, or https://www.revitapidocs.com/$Year/"
    exit 1
}

Write-Host "Revit $Year API docs: $($hits.Count) match(es) for '$Query'. Showing $([Math]::Min($Top, $hits.Count))."
foreach ($h in ($hits | Select-Object -First $Top)) {
    $m = $h.Node
    Write-Host ''
    Write-Host ("[{0}] {1}" -f $kindNames[$h.Id.Substring(0, 1)], $h.Id.Substring(2))
    # Use SelectSingleNode/SelectNodes: PowerShell's XML adapter turns text-only elements into
    # plain strings, so $m.summary.InnerText would silently come back empty.
    $s = $m.SelectSingleNode('summary'); if ($s) { Write-Host ("  Summary: {0}" -f (Clean $s.InnerText)) }
    foreach ($p in $m.SelectNodes('param')) { Write-Host ("  Param {0}: {1}" -f $p.GetAttribute('name'), (Clean $p.InnerText)) }
    $s = $m.SelectSingleNode('returns'); if ($s) { Write-Host ("  Returns: {0}" -f (Clean $s.InnerText)) }
    $s = $m.SelectSingleNode('remarks'); if ($s) { $r = Clean $s.InnerText; if ($r.Length -gt 600) { $r = $r.Substring(0, 600) + '...' }; Write-Host "  Remarks: $r" }
    foreach ($e in $m.SelectNodes('exception')) { Write-Host ("  Throws {0}: {1}" -f ($e.GetAttribute('cref') -replace '^T:', ''), (Clean $e.InnerText)) }
}
exit 0

<#
.SYNOPSIS
  INVENTORY step for am-markup-intake: list the markup files in a folder (or a list of files).

.DESCRIPTION
  inventory.ps1 -Path <folder or file> [-Path <more>] [-Json <out.json>] [-NoRecurse]
                [-ConvertTiff <folder>]

  Readable:        .pdf .jpg .jpeg .png
  Convert first:   .tif .tiff  Claude's Read tool cannot open TIFF. -ConvertTiff <folder>
                               writes each TIFF page as a PNG (System.Drawing, no admin)
                               and lists the PNGs as readable. The TIFF files stay unchanged.
                   .heic .heif Claude cannot read them; export as JPG from Photos or the phone.
  Other files are listed as "skipped" with their extension.

  PDF page count: read from the file without extra tools. The script counts page
  objects (/Type /Page) and the page tree total (/Count). When the file uses
  compressed object streams, both can be hidden: the count is then "unknown".
  Method values: "pages" (counted), "tree" (from /Count), "unknown".
  Only the first and last 8 MB of a large PDF are scanned, so the count can be
  marked "approx".

  Exit codes: 0 ok, 1 path not found or nothing supported.
  Windows PowerShell 5.1, no admin rights, ASCII only.
#>
param(
    [Parameter(Mandatory = $true)][string[]]$Path,
    [string]$Json,
    [switch]$NoRecurse,
    [int]$BigPages = 60,
    [int]$BigMB = 150,
    [string]$ConvertTiff
)
$ErrorActionPreference = 'Stop'
$supported = @('.pdf', '.jpg', '.jpeg', '.png')
$tiff = @('.tif', '.tiff')
$convert = @('.heic', '.heif', '.tif', '.tiff')

# TIFF page count, and optional conversion to one PNG for each page.
function Get-TiffPages([string]$file, [string]$outDir) {
    Add-Type -AssemblyName System.Drawing
    $img = [System.Drawing.Image]::FromFile($file)
    $made = @()
    try {
        $dim = New-Object System.Drawing.Imaging.FrameDimension $img.FrameDimensionsList[0]
        $n = $img.GetFrameCount($dim)
        if ($outDir) {
            if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
            $base = [IO.Path]::GetFileNameWithoutExtension($file)
            for ($i = 0; $i -lt $n; $i++) {
                [void]$img.SelectActiveFrame($dim, $i)
                $png = Join-Path $outDir ("{0}_p{1}.png" -f $base, ($i + 1))
                $img.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
                $made += $png
            }
        }
    } finally { $img.Dispose() }
    return @{ Pages = $n; Made = $made }
}
$cap = 8MB

function Get-PdfPages([string]$file) {
    $len = (Get-Item -LiteralPath $file).Length
    $fs = [IO.File]::OpenRead($file)
    try {
        $chunks = @()
        if ($len -le 2 * $cap) {
            $buf = New-Object byte[] $len
            [void]$fs.Read($buf, 0, $len)
            $chunks += , $buf
            $approx = $false
        } else {
            $head = New-Object byte[] $cap
            [void]$fs.Read($head, 0, $cap)
            [void]$fs.Seek(-$cap, [IO.SeekOrigin]::End)
            $tail = New-Object byte[] $cap
            [void]$fs.Read($tail, 0, $cap)
            $chunks += , $head
            $chunks += , $tail
            $approx = $true
        }
    } finally { $fs.Dispose() }
    # Latin-1 keeps one char per byte, so regex positions match bytes.
    $enc = [Text.Encoding]::GetEncoding(28591)
    $pages = 0; $tree = 0; $objStm = $false; $encrypted = $false
    foreach ($c in $chunks) {
        $t = $enc.GetString($c)
        $pages += ([regex]::Matches($t, '/Type\s*/Page(?![a-zA-Z])')).Count
        foreach ($m in [regex]::Matches($t, '/Type\s*/Pages\b[^>]*?/Count\s+(\d+)|/Count\s+(\d+)[^>]*?/Type\s*/Pages\b')) {
            $v = if ($m.Groups[1].Success) { [int]$m.Groups[1].Value } else { [int]$m.Groups[2].Value }
            if ($v -gt $tree) { $tree = $v }
        }
        if ($t -match '/Type\s*/ObjStm') { $objStm = $true }
        if ($t -match '/Encrypt\b') { $encrypted = $true }
    }
    # Incremental saves (Bluebeam) repeat page objects, so prefer the page tree total.
    if ($tree -gt 0) { $n = $tree; $how = 'tree' }
    elseif ($pages -gt 0 -and -not $objStm) { $n = $pages; $how = 'pages' }
    else { $n = $null; $how = 'unknown' }
    if ($approx -and $n) { $how = "$how (approx)" }
    return @{ Pages = $n; Method = $how; Encrypted = $encrypted }
}

$files = New-Object System.Collections.Generic.List[object]
foreach ($p in $Path) {
    if (-not (Test-Path -LiteralPath $p)) { Write-Host "FAIL: not found: $p"; exit 1 }
    $item = Get-Item -LiteralPath $p
    if ($item.PSIsContainer) {
        $found = if ($NoRecurse) { Get-ChildItem -LiteralPath $p -File } else { Get-ChildItem -LiteralPath $p -File -Recurse }
        foreach ($f in $found) { $files.Add($f) }
    } else { $files.Add($item) }
}

$rows = New-Object System.Collections.Generic.List[object]
foreach ($f in ($files | Sort-Object FullName)) {
    $ext = $f.Extension.ToLowerInvariant()
    $status = if ($supported -contains $ext) { 'ok' } elseif ($convert -contains $ext) { 'convert first' } else { 'skipped' }
    if ($status -eq 'skipped' -and @('.json', '.csv', '.html') -contains $ext -and $f.Name -like '*tracker*') { continue }
    $pages = $null; $method = ''; $note = ''
    if ($ext -eq '.pdf') {
        try {
            $r = Get-PdfPages $f.FullName
            $pages = $r.Pages; $method = $r.Method
            if ($r.Encrypted) { $note = 'encrypted: the annotation reader may need the password' }
        } catch { $method = 'unknown'; $note = "could not read: $($_.Exception.Message)" }
    } elseif ($status -eq 'ok') { $pages = 1; $method = 'image' }
    if ($status -eq 'convert first' -and $tiff -contains $ext) {
        try {
            $tr = Get-TiffPages $f.FullName $ConvertTiff
            $pages = $tr.Pages; $method = 'tiff frames'
            if ($ConvertTiff) {
                $note = "converted to $($tr.Made.Count) PNG page(s) in $ConvertTiff"
                foreach ($m in $tr.Made) {
                    $mi = Get-Item -LiteralPath $m
                    $rows.Add([pscustomobject]@{
                            file = $mi.FullName; name = $mi.Name; type = 'png'; status = 'ok'
                            sizeMB = [math]::Round($mi.Length / 1MB, 2); pages = 1; pageMethod = 'image'
                            note = "page of $($f.Name)"
                        })
                }
            } else { $note = 'TIFF: run again with -ConvertTiff <folder> to make PNG pages' }
        } catch { $note = "TIFF: could not open: $($_.Exception.Message)" }
    } elseif ($status -eq 'convert first') { $note = 'HEIC: export as JPG first' }
    $rows.Add([pscustomobject]@{
            file = $f.FullName; name = $f.Name; type = $ext.TrimStart('.'); status = $status
            sizeMB = [math]::Round($f.Length / 1MB, 2); pages = $pages; pageMethod = $method; note = $note
        })
}

$ok = @($rows | Where-Object { $_.status -eq 'ok' })
$totalPages = 0; $unknown = 0
foreach ($r in $ok) { if ($null -ne $r.pages) { $totalPages += [int]$r.pages } else { $unknown++ } }
$totalMB = [math]::Round((($ok | Measure-Object -Property sizeMB -Sum).Sum), 2)
$byType = @{}
foreach ($r in $rows) { $k = "$($r.type) ($($r.status))"; if ($byType.ContainsKey($k)) { $byType[$k]++ } else { $byType[$k] = 1 } }

Write-Host ("{0,-44} {1,-6} {2,8} {3,6}  {4}" -f 'File', 'Type', 'MB', 'Pages', 'Note')
foreach ($r in $rows) {
    $pg = if ($null -ne $r.pages) { "$($r.pages)" } else { '?' }
    $nm = if ($r.name.Length -gt 44) { $r.name.Substring(0, 41) + '...' } else { $r.name }
    $nt = if ($r.status -ne 'ok') { $r.status + $(if ($r.note) { ': ' + $r.note } else { '' }) } else { $r.note }
    Write-Host ("{0,-44} {1,-6} {2,8} {3,6}  {4}" -f $nm, $r.type, $r.sizeMB, $pg, $nt)
}
Write-Host ''
Write-Host ("By type: " + (($byType.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name) $($_.Value)" }) -join ', '))
Write-Host ("Readable: {0} file(s), {1} page(s){2}, {3} MB" -f $ok.Count, $totalPages, $(if ($unknown) { " + $unknown PDF(s) with unknown page count" } else { '' }), $totalMB)
$big = ($totalPages -gt $BigPages) -or ($totalMB -gt $BigMB) -or ($unknown -gt 0)
$batches = [math]::Max(1, [math]::Ceiling($totalPages / 10))
if ($big) { Write-Host ("LARGE SET: about {0} batch(es) of 10 pages. Propose batches to the user before you read." -f $batches) }

if ($Json) {
    $out = [pscustomobject]@{
        kind = 'markup-inventory'; files = $rows.ToArray(); readableFiles = $ok.Count
        totalPages = $totalPages; unknownPageCount = $unknown; totalMB = $totalMB; large = $big
        suggestedBatches = $batches
    }
    $text = $out | ConvertTo-Json -Depth 5
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($Json), $text, (New-Object Text.UTF8Encoding $false))
    Write-Host "OK: wrote $Json"
}
if ($ok.Count -eq 0) { Write-Host 'FAIL: no readable markup files (pdf, jpg, jpeg, png; convert tif and heic first)'; exit 1 }
exit 0

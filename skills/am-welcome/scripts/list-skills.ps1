# list-skills.ps1 - print "name<TAB>description<TAB>mode" for every am-* skill archi-magic ships.
# Read-only. Windows PowerShell 5.1. ASCII only.
# Reads the YAML frontmatter between the first two "---" lines of each skills\am-*\SKILL.md:
#   - next to this skill (this plugin), and
#   - in every other installed archi-magic / archi-magic-* plugin (installed_plugins.json, read
#     through scripts\lib\am-plugins.ps1, which follows CLAUDE_CONFIG_DIR). After the planned split
#     am-welcome lives in archi-magic-core and the Revit and Rhino skills in their own plugins.
# Skips am-welcome itself. A skill name found twice is listed once.
# mode is "user-only" when the frontmatter has "disable-model-invocation: true"
# (the user must type /<name>; Claude never picks it), otherwise "auto".
# This is the offline source; am-welcome merges in the pyrevit MCP list_skills when present.
# Exit codes: 0 = at least one skill listed, 2 = no sibling skills found.

[CmdletBinding()]
param(
    [switch]$IncludeSelf,
    # Test parameter: a fixture installed_plugins.json. '' = the real one.
    [string]$InstalledPluginsJson = ''
)

$ErrorActionPreference = 'Stop'

$skillDir  = Split-Path -Parent $PSScriptRoot      # ...\skills\am-welcome
$skillsDir = Split-Path -Parent $skillDir          # ...\skills
$selfName  = Split-Path -Leaf $skillDir

$skillRoots = @($skillsDir)
$lib = Join-Path (Split-Path -Parent $skillsDir) 'scripts\lib\am-plugins.ps1'
if (Test-Path -LiteralPath $lib) {
    try {
        . $lib
        if (-not $InstalledPluginsJson) { $InstalledPluginsJson = Get-AmInstalledPluginsPath }
        $inst = Read-AmInstalledPlugins $InstalledPluginsJson
        if ($inst.Ok) {
            $entries = Get-AmArchiMagicEntries $inst
            foreach ($e in $entries) {
                $d = Join-Path $e.InstallPath 'skills'
                if ($e.InstallPath -and (Test-Path -LiteralPath $d)) { $skillRoots += $d }
            }
        }
    } catch { Write-Warning "installed archi-magic plugins not read: $($_.Exception.Message)" }
}

$found = 0
$seenNames = @{}
$folders = @($skillRoots | Select-Object -Unique | ForEach-Object { Get-ChildItem -LiteralPath $_ -Directory -Filter 'am-*' }) | Sort-Object Name
foreach ($folder in $folders) {
    if ($seenNames.ContainsKey($folder.Name)) { continue }
    $seenNames[$folder.Name] = $true
    if (-not $IncludeSelf -and $folder.Name -eq $selfName) { continue }
    $file = Join-Path $folder.FullName 'SKILL.md'
    if (-not (Test-Path -LiteralPath $file)) {
        Write-Warning "$($folder.Name): no SKILL.md, skipped"
        continue
    }

    $lines = [System.IO.File]::ReadAllLines($file, [System.Text.Encoding]::UTF8)
    $fences = @()
    for ($i = 0; $i -lt $lines.Count -and $fences.Count -lt 2; $i++) {
        if ($lines[$i].Trim() -eq '---') { $fences += $i }
    }
    if ($fences.Count -lt 2) {
        Write-Warning "$($folder.Name): no frontmatter, skipped"
        continue
    }

    $name = $folder.Name
    $desc = ''
    $mode = 'auto'
    for ($i = $fences[0] + 1; $i -lt $fences[1]; $i++) {
        if ($lines[$i] -match '^disable-model-invocation:\s*true\s*$') {
            $mode = 'user-only'
        }
        elseif ($lines[$i] -match '^name:\s*(.+)$') {
            $name = $Matches[1].Trim().Trim('"', "'")
        }
        elseif ($lines[$i] -match '^description:\s*(.*)$') {
            $desc = $Matches[1].Trim()
            # Folded or literal block scalar, or continuation lines: join indented lines.
            if ($desc -match '^[>|][-+]?$') { $desc = '' }
            $j = $i + 1
            while ($j -lt $fences[1] -and $lines[$j] -match '^\s+\S') {
                $desc = ($desc + ' ' + $lines[$j].Trim()).Trim()
                $j++
            }
            $desc = $desc.Trim('"', "'")
        }
    }
    if (-not $desc) { Write-Warning "$name`: no description" }

    # Keep the output ASCII: replace common typographic characters, drop the rest.
    $desc = $desc -replace "[$([char]0x2018)$([char]0x2019)]", "'" `
                  -replace "[$([char]0x201C)$([char]0x201D)]", '"' `
                  -replace "[$([char]0x2013)$([char]0x2014)]", '-' `
                  -replace "$([char]0x2192)", '->' `
                  -replace '[^\x20-\x7E]', ''
    Write-Output ("{0}`t{1}`t{2}" -f $name, $desc, $mode)
    $found++
}

if ($found -eq 0) {
    Write-Warning "No am-* skills found under: $($skillRoots -join '; ')"
    exit 2
}
exit 0

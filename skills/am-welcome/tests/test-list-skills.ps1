<#
.SYNOPSIS
  Tests for am-welcome list-skills.ps1. Hermetic: fixture installed_plugins.json and temp plugin
  folders. Never reads the real ~/.claude.

  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-welcome\tests\test-list-skills.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$List = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\list-skills.ps1')).Path
$RepoSkills = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-list-skills-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Asserts = 0

function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name :`n$detail" }
}
function New-PluginWithSkills([string]$folder, [string[]]$skills) {
    foreach ($s in $skills) {
        $d = Join-Path $folder "skills\$s"
        New-Item -ItemType Directory -Force $d | Out-Null
        [IO.File]::WriteAllText((Join-Path $d 'SKILL.md'), "---`nname: $s`ndescription: Test skill $s.`n---`n`nBody.`n")
    }
    return $folder
}
function Write-Installed([hashtable]$map) {
    $o = @{ version = 2; plugins = @{} }
    foreach ($k in $map.Keys) { $o.plugins[$k] = @(@{ scope = 'user'; installPath = $map[$k]; version = 'aaaaaaaaaaaa' }) }
    $p = Join-Path $Root 'installed_plugins.json'
    [IO.File]::WriteAllText($p, ($o | ConvertTo-Json -Depth 6))
    return $p
}
function Invoke-List([string]$json) {
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $List -InstalledPluginsJson $json 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Names = @(($out -split "`r?`n") | Where-Object { $_ -match "`t" } | ForEach-Object { ($_ -split "`t")[0] }); Out = $out }
}

try {
    New-Item -ItemType Directory -Force $Root | Out-Null
    $repoNames = @(Get-ChildItem $RepoSkills -Directory -Filter 'am-*' | Where-Object { $_.Name -ne 'am-welcome' } | ForEach-Object Name | Sort-Object)

    # 1. No installed plugins (source checkout / CI): exactly the sibling skills of this repo.
    $r = Invoke-List (Join-Path $Root 'none.json')
    Assert-True 'no install: lists every sibling skill' ($r.Code -eq 0 -and (@($r.Names | Sort-Object) -join ',') -eq ($repoNames -join ',')) $r.Out

    # 2. Split layout: skills from installed archi-magic-revit and archi-magic-rhino are added once each.
    $revit = New-PluginWithSkills (Join-Path $Root 'cache\archi-magic-revit\aaaaaaaaaaaa') @('am-test-revit-only', 'am-model-health')
    $rhino = New-PluginWithSkills (Join-Path $Root 'cache\archi-magic-rhino\aaaaaaaaaaaa') @('am-test-rhino-only')
    $other = New-PluginWithSkills (Join-Path $Root 'cache\someone-else\aaaaaaaaaaaa') @('am-test-foreign')
    $j = Write-Installed @{ 'archi-magic-revit@archi-magic' = $revit; 'archi-magic-rhino@archi-magic' = $rhino; 'other-plugin@archi-magic' = $other }
    $r = Invoke-List $j
    Assert-True 'split: adds skills of installed archi-magic-* plugins' (($r.Names -contains 'am-test-revit-only') -and ($r.Names -contains 'am-test-rhino-only')) $r.Out
    Assert-True 'split: ignores non-archi-magic plugins' ($r.Names -notcontains 'am-test-foreign') $r.Out
    Assert-True 'split: a skill found twice is listed once' (@($r.Names | Where-Object { $_ -eq 'am-model-health' }).Count -eq 1) $r.Out
    Assert-True 'split: never lists am-welcome itself' ($r.Names -notcontains 'am-welcome') $r.Out
} finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Root
}

Write-Host ("{0} assertion(s), {1} failure(s)" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL: no assertions ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

<#
.SYNOPSIS
  Tests for hooks/update-check.ps1. Hermetic: temp plugin folders, temp cache and log folders.
  No real network: the release tag comes from -LatestTag, and "offline" uses a closed local port.

  powershell -NoProfile -ExecutionPolicy Bypass -File hooks\tests\test-update-check.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Hook = (Resolve-Path (Join-Path $PSScriptRoot '..\update-check.ps1')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-update-check-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$Offline = 'http://127.0.0.1:9/releases/latest'
$Old = 'aaaaaaaaaaaa'; $New = 'bbbbbbbbbbbb'
$script:Fail = 0; $script:Asserts = 0

function Invoke-Hook([string]$pluginRoot, [string[]]$extra = @(), [string]$json = '') {
    $cache = Join-Path $Root 'cache'
    # Never the real installed_plugins.json: default to a path that does not exist (folder-name fallback).
    if (-not $json) { $json = Join-Path $Root 'no-installed-plugins.json' }
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Hook -PluginRoot $pluginRoot -CacheDir $cache -InstalledPluginsJson $json @extra 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out.Trim() }
}
function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name : $detail" }
}
function Write-Cache([string]$installed, [string]$tag, [datetime]$when) {
    $dir = Join-Path $Root 'cache'
    New-Item -ItemType Directory -Force $dir | Out-Null
    $rec = [ordered]@{ installed = $installed; latest_tag = $tag; checked_at = $when.ToUniversalTime().ToString('o') }
    [IO.File]::WriteAllText((Join-Path $dir 'update-check.json'), (New-Object PSObject -Property $rec | ConvertTo-Json -Compress))
}
function Clear-Cache { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Root 'cache\update-check.json') }
function Get-LogText { (Get-ChildItem (Join-Path $Root 'logs') -Filter *.jsonl -ErrorAction SilentlyContinue | Get-Content -Raw) -join '' }

try {
    New-Item -ItemType Directory -Force $Root | Out-Null
    $env:ARCHI_MAGIC_LOG_DIR = Join-Path $Root 'logs'
    $installedRoot = Join-Path $Root "plugins\cache\archi-magic\archi-magic\$Old"
    New-Item -ItemType Directory -Force $installedRoot | Out-Null

    # 1. Outdated: one valid JSON object with both versions, exit 0.
    $r = Invoke-Hook $installedRoot @('-LatestTag', "r2026.10.22-$New")
    $j = $null; try { $j = $r.Out | ConvertFrom-Json } catch { }
    Assert-True 'outdated: exit 0' ($r.Code -eq 0) "exit $($r.Code)"
    Assert-True 'outdated: valid JSON' ($null -ne $j) $r.Out
    Assert-True 'outdated: systemMessage names both versions' ($j -and $j.systemMessage -match $Old -and $j.systemMessage -match $New) $r.Out
    Assert-True 'outdated: additionalContext for SessionStart' ($j -and $j.hookSpecificOutput.hookEventName -eq 'SessionStart' -and $j.hookSpecificOutput.additionalContext) $r.Out

    # 2. Up to date: no output.
    $r = Invoke-Hook $installedRoot @('-LatestTag', "r2026.10.22-$Old")
    Assert-True 'current: no output' ($r.Code -eq 0 -and $r.Out -eq '') "exit $($r.Code) out '$($r.Out)'"

    # 3. Source checkout (parent folder is not archi-magic): no check, no output.
    $src = Join-Path $Root 'github\archi-magic-src'
    New-Item -ItemType Directory -Force $src | Out-Null
    $r = Invoke-Hook $src @('-LatestTag', "r2026.10.22-$New")
    Assert-True 'source checkout: no output' ($r.Code -eq 0 -and $r.Out -eq '') $r.Out

    # 4. Opt-out.
    $env:ARCHI_MAGIC_NO_UPDATE_CHECK = '1'
    $r = Invoke-Hook $installedRoot @('-LatestTag', "r2026.10.22-$New")
    Remove-Item Env:\ARCHI_MAGIC_NO_UPDATE_CHECK
    Assert-True 'opt-out: no output' ($r.Code -eq 0 -and $r.Out -eq '') $r.Out

    # 5. Offline, no cache: no output, exit 0, a warn line in the log.
    Clear-Cache
    $r = Invoke-Hook $installedRoot @('-ApiUrl', $Offline)
    Assert-True 'offline: no output, exit 0' ($r.Code -eq 0 -and $r.Out -eq '') "exit $($r.Code) out '$($r.Out)'"
    Assert-True 'offline: logged as warn' ((Get-LogText) -match '"step":"update-check","level":"warn"') (Get-LogText)

    # 6. Fresh cache for this version: used without the network.
    Write-Cache "archi-magic=$Old" "r2026.10.22-$New" (Get-Date)
    $r = Invoke-Hook $installedRoot @('-ApiUrl', $Offline)
    Assert-True 'fresh cache: message without network' ($r.Out -match $New) $r.Out

    # 7. Cache written by another installed version (user updated): ignored, so no stale message.
    Write-Cache 'archi-magic=cccccccccccc' "r2026.10.22-$New" (Get-Date)
    $r = Invoke-Hook $installedRoot @('-ApiUrl', $Offline)
    Assert-True 'other-version cache: ignored' ($r.Out -eq '') $r.Out

    # 8. Expired cache: ignored.
    Write-Cache "archi-magic=$Old" "r2026.10.22-$New" ((Get-Date).AddHours(-30))
    $r = Invoke-Hook $installedRoot @('-ApiUrl', $Offline)
    Assert-True 'expired cache: ignored' ($r.Out -eq '') $r.Out

    # 9. Unexpected tag: no output, logged.
    Clear-Cache
    $r = Invoke-Hook $installedRoot @('-LatestTag', 'v1.2.3')
    Assert-True 'bad tag: no output' ($r.Code -eq 0 -and $r.Out -eq '') $r.Out
    Assert-True 'bad tag: logged' ((Get-LogText) -match 'unexpected release tag') (Get-LogText)

    # --- installed_plugins.json read (U1): every installed archi-magic* plugin is compared ---
    function Write-Installed([hashtable]$shas) {
        $o = @{ version = 2; plugins = @{} }
        foreach ($k in $shas.Keys) {
            $full = ($shas[$k] * 4).Substring(0, 40)
            $o.plugins[$k] = @(@{ scope = 'user'; installPath = (Join-Path $Root "plugins\cache\archi-magic\$($k.Split('@')[0])\$($shas[$k])"); version = $shas[$k]; gitCommitSha = $full })
        }
        $p = Join-Path $Root 'installed_plugins.json'
        [IO.File]::WriteAllText($p, ($o | ConvertTo-Json -Depth 6))
        return $p
    }
    Clear-Cache

    # 10. Meta only, read from installed_plugins.json: stale -> names archi-magic.
    $j = Write-Installed @{ 'archi-magic@archi-magic' = $Old; 'superpowers@archi-magic' = 'dddddddddddd' }
    $r = Invoke-Hook $installedRoot @('-LatestTag', "r2026.10.22-$New") $j
    $x = $null; try { $x = $r.Out | ConvertFrom-Json } catch { }
    Assert-True 'json meta stale: names archi-magic, not superpowers' ($x -and $x.systemMessage -match "archi-magic $Old" -and $x.systemMessage -notmatch 'superpowers') $r.Out
    Assert-True 'json meta stale: steps include /reload-plugins' ($x -and $x.systemMessage -match '/reload-plugins') $r.Out

    # 11. Split, core + rhino installed, only rhino behind: only rhino is named.
    $coreRoot = Join-Path $Root "plugins\cache\archi-magic\archi-magic-core\$New"; New-Item -ItemType Directory -Force $coreRoot | Out-Null
    $j = Write-Installed @{ 'archi-magic-core@archi-magic' = $New; 'archi-magic-rhino@archi-magic' = $Old }
    $r = Invoke-Hook $coreRoot @('-LatestTag', "r2026.10.22-$New") $j
    $x = $null; try { $x = $r.Out | ConvertFrom-Json } catch { }
    Assert-True 'core+rhino, rhino behind: names only rhino' ($x -and $x.systemMessage -match "archi-magic-rhino $Old" -and $x.systemMessage -notmatch 'archi-magic-core ') $r.Out

    # 12. Split, all installed plugins current: no output (also: hook runs from a core folder).
    $j = Write-Installed @{ 'archi-magic-core@archi-magic' = $New; 'archi-magic-rhino@archi-magic' = $New; 'archi-magic-revit@archi-magic' = $New }
    $r = Invoke-Hook $coreRoot @('-LatestTag', "r2026.10.22-$New") $j
    Assert-True 'split, all current: no output' ($r.Code -eq 0 -and $r.Out -eq '') $r.Out

    # 13. Partial update: core updated, revit not -> still notifies (does not go quiet), names revit.
    $j = Write-Installed @{ 'archi-magic-core@archi-magic' = $New; 'archi-magic-revit@archi-magic' = $Old }
    $r = Invoke-Hook $coreRoot @('-LatestTag', "r2026.10.22-$New") $j
    Assert-True 'partial update: names revit' ($r.Out -match "archi-magic-revit $Old") $r.Out

    # 14. Cache keyed by the installed set: a cache written for another set is ignored offline.
    Write-Cache "archi-magic-core=$New,archi-magic-revit=$New" "r2026.10.22-$New" (Get-Date)
    $r = Invoke-Hook $coreRoot @('-ApiUrl', $Offline) $j
    Assert-True 'cache for another installed set: ignored' ($r.Out -eq '') $r.Out
    Write-Cache "archi-magic-core=$New,archi-magic-revit=$Old" "r2026.10.22-$New" (Get-Date)
    $r = Invoke-Hook $coreRoot @('-ApiUrl', $Offline) $j
    Assert-True 'cache for this installed set: used offline' ($r.Out -match "archi-magic-revit $Old") $r.Out
} finally {
    Remove-Item Env:\ARCHI_MAGIC_LOG_DIR -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Root
}

Write-Host ("{0} assertion(s), {1} failure(s)" -f $script:Asserts, $script:Fail)
if ($script:Asserts -eq 0) { Write-Host 'FAIL: no assertions ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

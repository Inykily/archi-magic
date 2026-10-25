<#
.SYNOPSIS
  Tests for the am-doctor DEPS / DEPS_MISSING check. Hermetic: every case uses a temp copy of
  installed_plugins.json with temp install folders. Never touches the real ~/.claude files,
  never calls the network, never runs `claude plugin install`.

  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-doctor\tests\test-deps.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Doctor = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\doctor.ps1')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-doctor-deps-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Asserts = 0

function New-Plugin([string]$name, [string[]]$deps) {
    $dir = Join-Path $Root "cache\$name"
    New-Item -ItemType Directory -Force (Join-Path $dir '.claude-plugin') | Out-Null
    $man = @{ name = $name }
    if ($deps) { $man.dependencies = $deps }
    [IO.File]::WriteAllText((Join-Path $dir '.claude-plugin\plugin.json'), ($man | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    return $dir
}
function Write-Installed([hashtable]$plugins, [string]$path) {
    $o = @{ version = 2; plugins = @{} }
    foreach ($k in $plugins.Keys) { $o.plugins[$k] = @(@{ scope = 'user'; installPath = $plugins[$k]; version = '1.0.0' }) }
    [IO.File]::WriteAllText($path, ($o | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding $false))
}
function Invoke-Doctor([string]$json, [string]$settings, [string[]]$extra = @()) {
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Doctor -Only deps -InstalledPluginsJson $json -ClaudeSettingsJson $settings -LogDir (Join-Path $Root 'logs') @extra 2>&1 | Out-String
    return @{ Code = $LASTEXITCODE; Out = $out }
}
function Assert-Case([string]$name, $r, [int]$code, [string]$pattern) {
    $script:Asserts++
    $ok = ($r.Code -eq $code) -and ($r.Out -match $pattern)
    if ($ok) { Write-Host "PASS $name (exit $($r.Code))" }
    else { $script:Fail++; Write-Host "FAIL $name : exit $($r.Code), want $code and /$pattern/`n$($r.Out)" }
}

try {
    New-Item -ItemType Directory -Force $Root | Out-Null
    $am = New-Plugin 'archi-magic' @('superpowers', 'frontend-design')
    $sp = New-Plugin 'superpowers' @()
    $fd = New-Plugin 'frontend-design' @()
    $json = Join-Path $Root 'installed_plugins.json'
    $noSettings = Join-Path $Root 'no-settings.json'
    $all = @{ 'archi-magic@archi-magic' = $am; 'superpowers@archi-magic' = $sp; 'frontend-design@archi-magic' = $fd }

    # GREEN: both dependencies installed.
    Write-Installed $all $json
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'present -> GREEN' $r 0 '(?m)^DEPS \| ok \|.*superpowers@archi-magic, frontend-design@archi-magic'

    # RED: superpowers entry missing (the 0.1.0 -> 0.4.1 update case).
    $c = $all.Clone(); $c.Remove('superpowers@archi-magic'); Write-Installed $c $json
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'superpowers missing -> RED' $r 1 '(?m)^DEPS_MISSING \| error \|.*superpowers@archi-magic not installed.*\| claude plugin install'

    # RED: frontend-design entry exists but its install folder is gone.
    $gone = Join-Path $Root 'cache\deleted-frontend-design'
    $c = $all.Clone(); $c['frontend-design@archi-magic'] = $gone; Write-Installed $c $json
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'install folder missing -> RED' $r 1 '(?m)^DEPS_MISSING \| error \|.*frontend-design@archi-magic install folder missing'

    # RED: folder exists but has no plugin manifest (fails to load).
    $broken = Join-Path $Root 'cache\broken-sp'; New-Item -ItemType Directory -Force $broken | Out-Null
    $c = $all.Clone(); $c['superpowers@archi-magic'] = $broken; Write-Installed $c $json
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'manifest missing -> RED' $r 1 '(?m)^DEPS_MISSING \| error \|.*superpowers@archi-magic has no'

    # Unchecked: corrupt JSON is never shown as healthy.
    [IO.File]::WriteAllText($json, '{ not json', (New-Object Text.UTF8Encoding $false))
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'corrupt json -> unchecked' $r 2 '(?m)^DEPS \| unchecked \|'

    # Info: archi-magic not installed from a marketplace (for example a --plugin-dir run).
    Write-Installed @{ 'superpowers@archi-magic' = $sp } $json
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'archi-magic absent -> info' $r 0 '(?m)^DEPS \| info \|.*not in installed_plugins.json'

    # Info: archi-magic disabled in settings.json, dependencies not judged.
    $c = $all.Clone(); $c.Remove('superpowers@archi-magic'); Write-Installed $c $json
    $settings = Join-Path $Root 'settings.json'
    [IO.File]::WriteAllText($settings, '{"enabledPlugins":{"archi-magic@archi-magic":false}}', (New-Object Text.UTF8Encoding $false))
    $r = Invoke-Doctor $json $settings
    Assert-Case 'archi-magic disabled -> info' $r 0 '(?m)^DEPS \| info \|.*disabled'

    # -Fix DEPS_MISSING when nothing is missing: exits 0 without calling the CLI.
    Write-Installed $all $json
    $r = Invoke-Doctor $json $noSettings @('-Fix', 'DEPS_MISSING')
    Assert-Case 'fix with nothing missing -> no-op' $r 0 'Nothing to fix'

    # Split layout (docs/plans/2026-10-24-plugin-split.md): meta -> core/revit/rhino -> core -> superpowers.
    $meta  = New-Plugin 'meta' @('archi-magic-core', 'archi-magic-revit', 'archi-magic-rhino')
    $core  = New-Plugin 'core' @('superpowers', 'frontend-design')
    $revit = New-Plugin 'revit' @('archi-magic-core')
    $rhino = New-Plugin 'rhino' @('archi-magic-core')
    $split = @{ 'archi-magic@archi-magic' = $meta; 'archi-magic-core@archi-magic' = $core; 'archi-magic-revit@archi-magic' = $revit
                'archi-magic-rhino@archi-magic' = $rhino; 'superpowers@archi-magic' = $sp; 'frontend-design@archi-magic' = $fd }
    Write-Installed $split $json
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'split, all present -> GREEN' $r 0 '(?m)^DEPS \| ok \|.*archi-magic-core@archi-magic.*superpowers@archi-magic'

    # RED: the meta updated but its new dependency was never installed (update without /reload-plugins).
    $c = $split.Clone(); $c.Remove('archi-magic-core@archi-magic'); Write-Installed $c $json
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'split, core missing -> RED' $r 1 '(?m)^DEPS_MISSING \| error \|.*archi-magic-core@archi-magic not installed'

    # RED: transitive - core present but its own dependency gone.
    $c = $split.Clone(); $c.Remove('superpowers@archi-magic'); Write-Installed $c $json
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'split, transitive dep missing -> RED' $r 1 '(?m)^DEPS_MISSING \| error \|.*superpowers@archi-magic not installed'

    # RED: half-swapped cache - core's folder exists but lost its manifest during an interrupted update.
    $half = Join-Path $Root 'cache\half-core'; New-Item -ItemType Directory -Force (Join-Path $half 'skills') | Out-Null
    $c = $split.Clone(); $c['archi-magic-core@archi-magic'] = $half; Write-Installed $c $json
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'split, half-swapped core -> RED' $r 1 '(?m)^DEPS_MISSING \| error \|.*archi-magic-core@archi-magic has no'

    # Only core + rhino installed (opt-out of revit), no meta: checked from core and rhino.
    $c = @{ 'archi-magic-core@archi-magic' = $core; 'archi-magic-rhino@archi-magic' = $rhino; 'superpowers@archi-magic' = $sp; 'frontend-design@archi-magic' = $fd }
    Write-Installed $c $json
    $r = Invoke-Doctor $json $noSettings
    Assert-Case 'core+rhino only -> GREEN' $r 0 '(?m)^DEPS \| ok \|'

    # Default path follows CLAUDE_CONFIG_DIR (no -InstalledPluginsJson): the throwaway config is read, not the real one.
    $cfg = Join-Path $Root 'cfg'; New-Item -ItemType Directory -Force (Join-Path $cfg 'plugins') | Out-Null
    $c = $split.Clone(); $c.Remove('archi-magic-rhino@archi-magic'); Write-Installed $c (Join-Path $cfg 'plugins\installed_plugins.json')
    $env:CLAUDE_CONFIG_DIR = $cfg
    try {
        $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Doctor -Only deps -LogDir (Join-Path $Root 'logs') 2>&1 | Out-String
        $r = @{ Code = $LASTEXITCODE; Out = $out }
    } finally { Remove-Item Env:\CLAUDE_CONFIG_DIR -ErrorAction SilentlyContinue }
    Assert-Case 'CLAUDE_CONFIG_DIR default path -> reads the throwaway config' $r 1 '(?m)^DEPS_MISSING \| error \|.*archi-magic-rhino@archi-magic not installed'
} finally {
    Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "$script:Asserts case(s), $script:Fail failed"
if ($script:Fail -or $script:Asserts -eq 0) { exit 1 }
exit 0

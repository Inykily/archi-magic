<#
.SYNOPSIS
  Shared, read-only reader for Claude Code's installed-plugin records. Dot-source it, then call the
  Am* functions. Used by am-doctor (dependency check), hooks/update-check.ps1 (update notice),
  am-welcome list-skills.ps1 and am-rhino-setup.

.DESCRIPTION
  Paths follow CLAUDE_CONFIG_DIR when it is set (Claude Code's config folder), else
  %USERPROFILE%\.claude. Nothing here writes a file or calls the network.

  archi-magic is one plugin today (archi-magic@<marketplace>). The planned split
  (docs/plans/2026-10-24-plugin-split.md) adds archi-magic-core, -revit and -rhino. Every function
  here treats any installed "archi-magic" or "archi-magic-*" entry as part of archi-magic, so the
  same code works before and after the split.

  Dot-sourcing runs in the caller's scope: every name here starts with Am.
#>

function Get-AmClaudeDir {
    if ($env:CLAUDE_CONFIG_DIR) { return $env:CLAUDE_CONFIG_DIR }
    return (Join-Path $env:USERPROFILE '.claude')
}

function Get-AmInstalledPluginsPath { return (Join-Path (Get-AmClaudeDir) 'plugins\installed_plugins.json') }
function Get-AmSettingsPath { return (Join-Path (Get-AmClaudeDir) 'settings.json') }

function Test-AmPluginName([string]$Name) {
    # The plugin part of "<plugin>@<marketplace>": archi-magic or archi-magic-<part>.
    return ($Name -eq 'archi-magic' -or $Name -like 'archi-magic-*')
}

function Read-AmInstalledPlugins([string]$Path) {
    # Returns @{ Ok; Error; Entries = ordered map key -> @{ Key; Name; Market; InstallPath; Sha } }.
    # Sha is the 12-character commit (gitCommitSha, else version when it looks like a commit).
    $r = @{ Ok = $false; Error = ''; Entries = [ordered]@{} }
    if (-not (Test-Path -LiteralPath $Path)) { $r.Error = 'not found'; return $r }
    try { $j = [IO.File]::ReadAllText($Path) | ConvertFrom-Json } catch { $r.Error = "unreadable: $($_.Exception.Message)"; return $r }
    if (-not $j -or -not $j.plugins) { $r.Error = "no 'plugins' object"; return $r }
    foreach ($p in $j.plugins.PSObject.Properties) {
        $e = @($p.Value) | Select-Object -Last 1
        if (-not $e) { continue }
        $at = $p.Name.IndexOf('@')
        $sha = ''
        if ($e.gitCommitSha -and [string]$e.gitCommitSha -match '^[0-9a-f]{12}') { $sha = ([string]$e.gitCommitSha).Substring(0, 12) }
        elseif ($e.version -and [string]$e.version -match '^[0-9a-f]{12}$') { $sha = [string]$e.version }
        $r.Entries[$p.Name] = @{
            Key = $p.Name
            Name = $(if ($at -gt 0) { $p.Name.Substring(0, $at) } else { $p.Name })
            Market = $(if ($at -gt 0) { $p.Name.Substring($at + 1) } else { '' })
            InstallPath = [string]$e.installPath
            Sha = $sha
        }
    }
    $r.Ok = $true
    return $r
}

function Get-AmDisabledKeys([string]$SettingsPath) {
    # Keys set to false in enabledPlugins. An unreadable settings.json gives an empty list.
    $out = @()
    if (-not $SettingsPath -or -not (Test-Path -LiteralPath $SettingsPath)) { return , $out }
    try {
        $s = [IO.File]::ReadAllText($SettingsPath) | ConvertFrom-Json
        if ($s.enabledPlugins) { foreach ($p in $s.enabledPlugins.PSObject.Properties) { if ($p.Value -eq $false) { $out += $p.Name } } }
    } catch { }
    return , $out
}

function Get-AmManifestDeps([string]$ManifestPath) {
    # Dependency names from a plugin.json ("name", "name@market" or { name, marketplace }). $null if unreadable.
    if (-not $ManifestPath -or -not (Test-Path -LiteralPath $ManifestPath)) { return $null }
    try {
        $man = [IO.File]::ReadAllText($ManifestPath) | ConvertFrom-Json
        return , @(@($man.dependencies) | ForEach-Object {
            if ($_ -is [string]) { $_ } elseif ($_.name) { if ($_.marketplace) { "$($_.name)@$($_.marketplace)" } else { [string]$_.name } }
        } | Where-Object { $_ })
    } catch { return $null }
}

function Get-AmArchiMagicEntries($Installed) {
    # Installed archi-magic and archi-magic-* entries, meta first.
    $all = @($Installed.Entries.Values | Where-Object { Test-AmPluginName $_.Name })
    return , @(@($all | Where-Object { $_.Name -eq 'archi-magic' }) + @($all | Where-Object { $_.Name -ne 'archi-magic' } | Sort-Object { $_.Name }))
}

function Get-AmDepsState {
    # Walks the dependency tree from every installed archi-magic* plugin (transitively) and reports
    # each needed plugin that is missing or broken on disk. A plugin is broken ("failed to load") when
    # its installPath or installPath\.claude-plugin\plugin.json is gone; this also catches a
    # half-swapped cache after an interrupted update.
    # Returns @{ State = ok|missing|unchecked|notinstalled|disabled; Root; Missing = @(keys); Evidence }.
    param([string]$InstalledPluginsJson, [string]$SettingsJson, [string]$FallbackManifest = '',
          [string[]]$KnownDeps = @('superpowers', 'frontend-design'))
    $r = @{ State = 'unchecked'; Root = ''; Missing = @(); Evidence = '' }
    $inst = Read-AmInstalledPlugins $InstalledPluginsJson
    if (-not $inst.Ok) {
        if ($inst.Error -eq 'not found') { $r.State = 'notinstalled'; $r.Evidence = "$InstalledPluginsJson not found; archi-magic is not installed from a marketplace"; return $r }
        $r.Evidence = "could not read $InstalledPluginsJson ($($inst.Error))"; return $r
    }
    $roots = Get-AmArchiMagicEntries $inst
    if ($roots.Count -eq 0) { $r.State = 'notinstalled'; $r.Evidence = 'archi-magic is not in installed_plugins.json (not installed from a marketplace)'; return $r }
    $r.Root = $roots[0].Key
    $disabled = Get-AmDisabledKeys $SettingsJson
    $active = @($roots | Where-Object { $disabled -notcontains $_.Key })
    if ($active.Count -eq 0) { $r.State = 'disabled'; $r.Evidence = "$($roots[0].Key) is installed but disabled in settings.json"; return $r }

    $missing = @(); $why = @(); $okList = @()
    $seen = @{}
    $queue = New-Object System.Collections.Generic.Queue[string]
    foreach ($e in $active) { $queue.Enqueue($e.Key) }
    $usedFallback = $false
    while ($queue.Count -gt 0) {
        $key = $queue.Dequeue()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $e = $inst.Entries[$key]
        if (-not $e) { $missing += $key; $why += "$key not installed"; continue }
        if (-not $e.InstallPath -or -not (Test-Path -LiteralPath $e.InstallPath)) { $missing += $key; $why += "$key install folder missing ($($e.InstallPath))"; continue }
        $man = Join-Path $e.InstallPath '.claude-plugin\plugin.json'
        if (-not (Test-Path -LiteralPath $man)) { $missing += $key; $why += "$key has no .claude-plugin\plugin.json (fails to load)"; continue }
        if ($key -ne $r.Root) { $okList += $key }
        $deps = Get-AmManifestDeps $man
        if ($null -eq $deps -and $e.Name -eq 'archi-magic') {
            $deps = Get-AmManifestDeps $FallbackManifest
            if ($null -eq $deps) { $deps = $KnownDeps }
            $usedFallback = $true
        }
        foreach ($d in @($deps)) { $queue.Enqueue($(if ($d -match '@') { $d } else { "$d@$($e.Market)" })) }
    }
    $r.Missing = $missing
    if ($missing.Count) { $r.State = 'missing'; $r.Evidence = "$($r.Root) needs: $($why -join '; ')" }
    else {
        $r.State = 'ok'
        $r.Evidence = "$($r.Root) dependencies installed: $($okList -join ', ')"
        if ($usedFallback) { $r.Evidence += ' (dependency list from this copy: installed manifest unreadable)' }
    }
    return $r
}

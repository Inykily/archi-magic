<#
.SYNOPSIS
  archi-magic SessionStart hook: tell the user when a newer archi-magic release exists.

.DESCRIPTION
  Compares the installed version (the commit folder name under ...\plugins\cache\<marketplace>\archi-magic\)
  with the latest GitHub release tag (r<yyyy.MM.dd>-<sha12>). At most one GitHub API call per
  installed version per -MaxAgeHours (cache: %LOCALAPPDATA%\archi-magic\update-check.json).

  Output: nothing when up to date, offline, or not an installed copy. When outdated, one JSON object:
  systemMessage (shown to the user) and additionalContext (for Claude).
  Never blocks a session: always exit 0. Every failure goes to the shared archi-magic log.
  Opt out: set ARCHI_MAGIC_NO_UPDATE_CHECK=1.

  Test parameters: -PluginRoot, -CacheDir, -LatestTag (skips the network), -ApiUrl.
#>
param(
    [string]$PluginRoot = $env:CLAUDE_PLUGIN_ROOT,
    [string]$CacheDir = $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'archi-magic' } else { '' }),
    [string]$LatestTag = '',
    [string]$ApiUrl = 'https://api.github.com/repos/zsenarchitect/archi-magic/releases/latest',
    [int]$MaxAgeHours = 24
)
$ErrorActionPreference = 'Stop'

function Write-Log([string]$Level, [string]$Message, [hashtable]$Data) {
    try {
        . (Join-Path $PSScriptRoot '..\scripts\lib\am-log.ps1')
        # Write-AmLog warns on a log failure; keep stdout clean for the hook JSON.
        Write-AmLog -Skill 'hooks' -Step 'update-check' -Level $Level -Message $Message -Data $Data 3>$null
    } catch { }
}

try {
    if ($env:ARCHI_MAGIC_NO_UPDATE_CHECK -eq '1' -or -not $PluginRoot) { exit 0 }

    # Only an installed copy has a commit folder as its version. A source checkout or pinned version: no check.
    $installed = Split-Path -Leaf $PluginRoot.TrimEnd('\', '/')
    $parent = Split-Path -Leaf (Split-Path -Parent $PluginRoot.TrimEnd('\', '/'))
    if ($parent -ne 'archi-magic' -or $installed -notmatch '^[0-9a-f]{12}$') { exit 0 }

    $cacheFile = if ($CacheDir) { Join-Path $CacheDir 'update-check.json' } else { '' }
    $tag = $LatestTag
    if (-not $tag -and $cacheFile -and (Test-Path -LiteralPath $cacheFile)) {
        try {
            $c = [IO.File]::ReadAllText($cacheFile) | ConvertFrom-Json
            $age = (Get-Date).ToUniversalTime() - [datetime]::Parse($c.checked_at).ToUniversalTime()
            # The cache is valid only for the version that wrote it, so an update triggers a fresh check.
            if ($c.installed -eq $installed -and $c.latest_tag -and $age.TotalHours -lt $MaxAgeHours) { $tag = [string]$c.latest_tag }
        } catch { }
    }
    if (-not $tag) {
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            $rel = Invoke-RestMethod -Uri $ApiUrl -TimeoutSec 4 -UseBasicParsing -Headers @{ 'User-Agent' = 'archi-magic-update-check' }
            $tag = [string]$rel.tag_name
        } catch {
            Write-Log 'warn' ('Update check skipped: ' + $_.Exception.Message) @{ installed = $installed }
            exit 0
        }
        if ($cacheFile) {
            try {
                if (-not (Test-Path -LiteralPath $CacheDir)) { New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null }
                $rec = [ordered]@{ installed = $installed; latest_tag = $tag; checked_at = (Get-Date).ToUniversalTime().ToString('o') }
                [IO.File]::WriteAllText($cacheFile, (New-Object PSObject -Property $rec | ConvertTo-Json -Compress))
            } catch { Write-Log 'warn' ('Update check cache not written: ' + $_.Exception.Message) $null }
        }
    }

    $m = [regex]::Match($tag, '^r\d{4}\.\d{2}\.\d{2}-([0-9a-f]{12})$')
    if (-not $m.Success) {
        Write-Log 'warn' "Update check: unexpected release tag '$tag'" @{ installed = $installed }
        exit 0
    }
    $latest = $m.Groups[1].Value
    if ($latest -eq $installed) { exit 0 }

    Write-Log 'info' 'Update available' @{ installed = $installed; latest = $latest }
    $user = "archi-magic update available (installed $installed, latest $latest). " +
            'To update: type /plugin, open the Marketplaces tab, select archi-magic, choose Update marketplace. ' +
            'Then start a new session. To get updates by itself, choose Enable auto-update there.'
    $ctx = "archi-magic is out of date: installed $installed, latest release $tag. " +
           'If the user asks about it: /plugin > Marketplaces > archi-magic > Update marketplace (or Installed > archi-magic > Update now), then a new session. ' +
           '"/plugin marketplace update archi-magic" alone refreshes the listing only and does not update the plugin. Do not update plugins without the user asking.'
    $out = [ordered]@{
        systemMessage      = $user
        hookSpecificOutput = [ordered]@{ hookEventName = 'SessionStart'; additionalContext = $ctx }
    }
    [Console]::Out.Write((New-Object PSObject -Property $out | ConvertTo-Json -Compress -Depth 3))
} catch {
    Write-Log 'error' ('Update check failed: ' + $_.Exception.Message) $null
}
exit 0

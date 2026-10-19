<#
.SYNOPSIS
  Install McNeel's Rhino MCP plugin (Rhino-MCP-Platform) per-user, connect it to
  Claude Code, and make Claude ask before every code-running Rhino tool.

.DESCRIPTION
  Safe to re-run. Steps (default: Install, Connect, Verify, in this order):
    -Install   Run 'Yak.exe install Rhino-MCP-Platform' for the current user
               (never --all-users). Skipped if the package is already installed
               (use -Force to run it again).
    -Connect   Copy the MCP router to %APPDATA%\McNeel\Rhinoceros\ai\bin if Rhino has
               not done it yet, register it with Claude Code (user scope, server name
               'rhino', full path), then run -AskRules.
    -AskRules  Merge permissions.ask rules for mcp__rhino__run_python, run_csharp and
               run_command into the Claude Code user settings (backup first, never
               drops existing keys or rules, no write when nothing changes).
    -Verify    Print the final state. Read-only.

  Never needs admin. Never starts, stops or kills Rhino.

  Exit codes: 0 ok, 2 required Rhino version not installed, 3 plugin install failed,
  4 MCP registration incomplete, 5 settings.json not changed (invalid JSON or
  unexpected shape), 6 verify found problems.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\rhino-setup.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File .\rhino-setup.ps1 -Verify
  powershell -NoProfile -ExecutionPolicy Bypass -File .\rhino-setup.ps1 -AskRules -SettingsPath C:\temp\settings.json
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Connect,
    [switch]$AskRules,
    [switch]$Verify,
    [switch]$Force,
    [ValidateSet('8', '9')][string]$RhinoVersion = '8',
    [string]$SettingsPath = (Join-Path $env:USERPROFILE '.claude\settings.json')
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if (-not ($Install -or $Connect -or $AskRules -or $Verify)) {
    $Install = $true; $Connect = $true; $Verify = $true
}
if ($Connect) { $AskRules = $true }

$Stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$WorkDir = Join-Path $env:TEMP "rhino-setup\$Stamp"
New-Item -ItemType Directory -Force $WorkDir | Out-Null
$LogFile = Join-Path $WorkDir 'setup.log'
Start-Transcript -Path $LogFile -Append | Out-Null

$ServerName  = 'rhino'      # McNeel's own name (RouterMcpConfig.ServerName); MCPConnect uses it too.
$PackageName = 'Rhino-MCP-Platform'
$AskList     = @('run_python', 'run_csharp', 'run_command') | ForEach-Object { "mcp__${ServerName}__$_" }
$RhinoData   = Join-Path $env:APPDATA 'McNeel\Rhinoceros'
$BinDir      = Join-Path $RhinoData 'ai\bin'
$StagedExe   = Join-Path $BinDir 'rhino-mcp-router.exe'
$Rid         = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'win-arm64' } else { 'win-x64' }
$script:Problems = New-Object System.Collections.Generic.List[string]

function Say($msg)  { Write-Host "[rhino-setup] $msg" }
function Warn($msg) { Write-Host "[rhino-setup] WARNING: $msg" -ForegroundColor Yellow; $script:Problems.Add($msg) }
function Fail($code, $msg) {
    Write-Host "[rhino-setup] FAILED: $msg" -ForegroundColor Red
    Say "Log: $LogFile"
    Stop-Transcript | Out-Null
    exit $code
}

# Native exes write to stderr; with EAP=Stop, PS 5.1 turns that into a terminating error.
function Invoke-Native([string]$Exe, [string[]]$ArgList) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = (& $Exe @ArgList 2>&1 | ForEach-Object { "$_" }) -join "`n"
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $old }
    return [pscustomobject]@{ Out = $out; Code = $code }
}

function Get-RhinoDirs([string]$Version) {
    if ($Version -eq '8') { $names = @('Rhino 8') } else { $names = @('Rhino 9', 'Rhino 9 BETA', 'Rhino 9 WIP') }
    $found = @()
    foreach ($n in $names) {
        $d = Join-Path $env:ProgramFiles $n
        if (Test-Path (Join-Path $d 'System\Rhino.exe')) { $found += $d }
    }
    return $found
}

function Get-PackageVersions([string]$Version) {
    $base = Join-Path $RhinoData "packages\$Version.0\$PackageName"
    if (-not (Test-Path $base)) { return @() }
    return @(Get-ChildItem $base -Directory | Sort-Object { try { [version]($_.Name -replace '[^\d\.].*$', '') } catch { [version]'0.0' } } -Descending)
}

function Find-RouterPayload {
    # Same search as McNeel's router-launcher.mjs: Rhino 9 first, then 8, newest package first.
    foreach ($v in '9', '8') {
        foreach ($p in (Get-PackageVersions $v)) {
            $dir = Join-Path $p.FullName "router\$Rid"
            if (Test-Path (Join-Path $dir 'rhino-mcp-router.exe')) { return $dir }
        }
    }
    return $null
}

function Find-ClaudeCli {
    # The Claude desktop app's own exe (AnthropicClaude\claude.exe) is NOT the CLI. Never use it.
    $cmd = Get-Command claude -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch 'AnthropicClaude' } | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    foreach ($c in @("$env:USERPROFILE\.local\bin\claude.exe", "$env:APPDATA\npm\claude.cmd")) {
        if (Test-Path $c) { return $c }
    }
    $bundled = Get-ChildItem (Join-Path $env:APPDATA 'Claude\claude-code') -Recurse -Filter claude.exe -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($bundled) { return $bundled.FullName }
    return $null
}

function Read-JsonFile([string]$Path) {
    # Returns @{ Ok; Obj; Text; Error }. Reads UTF-8 explicitly (PS 5.1 default is ANSI).
    $text = [IO.File]::ReadAllText($Path, (New-Object Text.UTF8Encoding $false))
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
    if ($text.Trim().Length -eq 0) { return @{ Ok = $false; Error = 'file is empty'; Text = $text } }
    try { $obj = $text | ConvertFrom-Json } catch { return @{ Ok = $false; Error = $_.Exception.Message; Text = $text } }
    if (-not ($obj -is [System.Management.Automation.PSCustomObject])) {
        return @{ Ok = $false; Error = 'top level is not a JSON object'; Text = $text }
    }
    return @{ Ok = $true; Obj = $obj; Text = $text }
}

function Get-AskRules($obj) {
    if (-not $obj) { return @() }
    $p = $obj.PSObject.Properties['permissions']
    if (-not $p -or -not $p.Value) { return @() }
    $a = $p.Value.PSObject.Properties['ask']
    if (-not $a -or $null -eq $a.Value) { return @() }
    return @($a.Value)
}

function Merge-AskRules([string]$Path, [string[]]$Rules) {
    Say "Settings file: $Path"
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    $exists = Test-Path $Path
    if ($exists) {
        $r = Read-JsonFile $Path
        if (-not $r.Ok) { Fail 5 "Not valid JSON ($($r.Error)). Nothing was written. Fix the file, or add the ask rules by hand: $($Rules -join ', ')" }
        $obj = $r.Obj
    } else {
        $obj = New-Object PSObject
    }
    $before = $obj | ConvertTo-Json -Depth 100 -Compress

    $createdPerm = $false; $createdAsk = $false
    $permProp = $obj.PSObject.Properties['permissions']
    if (-not $permProp) {
        $obj | Add-Member -NotePropertyName permissions -NotePropertyValue (New-Object PSObject)
        $createdPerm = $true
    } elseif (-not ($permProp.Value -is [System.Management.Automation.PSCustomObject])) {
        Fail 5 "'permissions' is not a JSON object. Nothing was written."
    }
    $perm = $obj.permissions
    $askProp = $perm.PSObject.Properties['ask']
    if (-not $askProp) {
        $perm | Add-Member -NotePropertyName ask -NotePropertyValue @()
        $createdAsk = $true
        $current = @()
    } elseif (-not ($askProp.Value -is [System.Array])) {
        Fail 5 "'permissions.ask' is not a JSON array. Nothing was written."
    } else {
        $current = @($askProp.Value)
    }

    $missing = @($Rules | Where-Object { $current -notcontains $_ })
    if ($missing.Count -eq 0) {
        Say 'Ask rules already present. settings.json not changed.'
        return
    }
    $perm.ask = [object[]]($current + $missing)
    $newText = $obj | ConvertTo-Json -Depth 100

    # Semantic guard: the new JSON minus our additions must equal the original.
    $check = $newText | ConvertFrom-Json
    $left = @($check.permissions.ask | Where-Object { $missing -notcontains $_ })
    if ($createdAsk) { $check.permissions.PSObject.Properties.Remove('ask') } else { $check.permissions.ask = [object[]]$left }
    if ($createdPerm) { $check.PSObject.Properties.Remove('permissions') }
    $after = $check | ConvertTo-Json -Depth 100 -Compress
    if ($after -ne $before) { Fail 5 'Merge self-check failed: the new JSON would change more than permissions.ask. Nothing was written.' }

    if ($exists) {
        $backup = "$Path.am-rhino-backup-$Stamp"
        Copy-Item $Path $backup -Force
        Say "Backup: $backup"
    }
    $tmp = "$Path.tmp-$Stamp"
    try {
        [IO.File]::WriteAllText($tmp, $newText, (New-Object Text.UTF8Encoding $false))
        # [NullString]::Value: a plain $null becomes "" for a string parameter, which Replace rejects.
        if ($exists) { [IO.File]::Replace($tmp, $Path, [NullString]::Value) } else { Move-Item $tmp $Path }
    } catch {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        Fail 5 "Could not write $Path ($($_.Exception.Message)). The original file is unchanged."
    }

    $re = Read-JsonFile $Path
    if (-not $re.Ok) { Fail 5 "After write, $Path does not parse ($($re.Error)). Restore it from $backup." }
    $now = Get-AskRules $re.Obj
    foreach ($rule in $Rules) { if ($now -notcontains $rule) { Fail 5 "After write, ask rule '$rule' is missing." } }
    Say "Added ask rule(s): $($missing -join ', ')"
}

Say "Log file: $LogFile"
$rhinoDirs = @(Get-RhinoDirs $RhinoVersion)

# ---------------------------------------------------------------- Install
if ($Install) {
    Say "== Install $PackageName for Rhino $RhinoVersion =="
    if ($rhinoDirs.Count -eq 0) { Fail 2 "Rhino $RhinoVersion is not installed under $env:ProgramFiles. Install it from https://www.rhino3d.com/download first." }
    $yak = Join-Path $rhinoDirs[0] 'System\Yak.exe'
    if (-not (Test-Path $yak)) { Fail 3 "Yak.exe not found at $yak." }
    $have = @(Get-PackageVersions $RhinoVersion)
    if ($have.Count -gt 0 -and -not $Force) {
        Say "$PackageName $($have[0].Name) is already installed for Rhino $RhinoVersion. Skipping (use -Force to run yak install again)."
    } else {
        Say "Running: `"$yak`" install $PackageName (current user only)"
        $r = Invoke-Native $yak @('install', $PackageName)
        $r.Out -split "`n" | ForEach-Object { Say "yak: $_" }
        $have = @(Get-PackageVersions $RhinoVersion)
        if ($r.Code -ne 0 -or $have.Count -eq 0) {
            Say 'Manual install (no admin needed):'
            Say "  1. Open Rhino $RhinoVersion."
            Say '  2. Type PackageManager and press Enter.'
            Say "  3. Search for $PackageName and click Install."
            Say '  4. Close and open Rhino again, then run this script with -Connect.'
            Fail 3 "yak install exited $($r.Code)."
        }
        Say "Installed $PackageName $($have[0].Name)."
    }
    if (Get-Process Rhino -ErrorAction SilentlyContinue) { Say 'Rhino is running: close and open it again so it loads the plugin.' }
}

# ---------------------------------------------------------------- Connect
if ($Connect) {
    Say '== Connect the Rhino MCP router to Claude Code =='
    if (-not (Test-Path $StagedExe)) {
        $payload = Find-RouterPayload
        if (-not $payload) { Fail 4 "No router found. Run with -Install first, or open Rhino once so the plugin copies it to $BinDir." }
        # Same copy the plugin and McNeel's launcher do: the stable path survives plugin updates.
        New-Item -ItemType Directory -Force $BinDir | Out-Null
        $files = @(Get-ChildItem $payload -Recurse -File | Where-Object { $_.Name -ne 'rhino-mcp-router.exe' }) + @(Get-Item (Join-Path $payload 'rhino-mcp-router.exe'))
        foreach ($f in $files) {
            $dst = Join-Path $BinDir $f.FullName.Substring($payload.Length).TrimStart('\')
            New-Item -ItemType Directory -Force (Split-Path -Parent $dst) | Out-Null
            Copy-Item $f.FullName $dst -Force
        }
        Say "Copied router from $payload to $BinDir"
    } else {
        Say "Router: $StagedExe"
    }

    $claude = Find-ClaudeCli
    if (-not $claude) {
        Warn "Claude Code CLI not found. Open Claude Code once, then run -Connect again. Or run: claude mcp add $ServerName -s user -- `"$StagedExe`""
    } else {
        Say "Claude Code CLI: $claude"
        $addArgs = @('mcp', 'add', $ServerName, '-s', 'user', '--', $StagedExe)
        if ($RhinoVersion -eq '9') { $addArgs += @('--default-version', '9') }
        $get = Invoke-Native $claude @('mcp', 'get', $ServerName)
        $okPath = $get.Out -match [regex]::Escape($StagedExe)
        $okVer  = ($RhinoVersion -eq '9') -eq ($get.Out -match '--default-version\s+9')
        if ($get.Code -eq 0 -and $okPath -and $okVer) {
            Say "MCP server '$ServerName' already registered with this router."
        } else {
            if ($get.Code -eq 0) {
                if ($get.Out -match 'Scope:\s*User') {
                    Say "Replacing the user-scope '$ServerName' registration that uses another command."
                    Invoke-Native $claude @('mcp', 'remove', $ServerName, '-s', 'user') | Out-Null
                } else {
                    Warn "An MCP server named '$ServerName' exists in another scope (local or project). It can hide this one:`n$($get.Out)"
                }
            }
            $add = Invoke-Native $claude $addArgs
            Say $add.Out
            $get = Invoke-Native $claude @('mcp', 'get', $ServerName)
            if ($get.Code -ne 0 -or $get.Out -notmatch [regex]::Escape($StagedExe)) { Fail 4 "Could not register the '$ServerName' MCP server with Claude Code." }
            Say "MCP server '$ServerName' registered (user scope)."
        }
    }
}

# ---------------------------------------------------------------- AskRules
if ($AskRules) {
    Say '== Ask before code-running Rhino tools =='
    Merge-AskRules $SettingsPath $AskList
}

# ---------------------------------------------------------------- Verify
if ($Verify) {
    Say '== Verify =='
    if ($rhinoDirs.Count -gt 0) { Say "Rhino ${RhinoVersion}: $($rhinoDirs -join ', ')" } else { Warn "Rhino $RhinoVersion is not installed." }
    if ($RhinoVersion -eq '8') {
        $r9 = @(Get-RhinoDirs '9')
        if ($r9.Count -gt 0) { Say "Also found Rhino 9: $($r9 -join ', '). Not configured (run with -RhinoVersion 9 to use it)." }
    }
    $running = @(Get-Process Rhino -ErrorAction SilentlyContinue)
    Say "Rhino windows open: $($running.Count)"
    if ($running.Count -gt 1) { Say 'More than one Rhino is open. Claude can edit a different document than the one you look at.' }

    $pk = @(Get-PackageVersions $RhinoVersion)
    if ($pk.Count -gt 0) { Say "${PackageName}: $(($pk | ForEach-Object Name) -join ', ') (Rhino $RhinoVersion)" } else { Warn "$PackageName is not installed for Rhino $RhinoVersion. Run -Install." }
    if (Test-Path $StagedExe) { Say "Router: $StagedExe" } else { Warn "Router not found at $StagedExe. Run -Connect, or open Rhino once." }

    $claude = Find-ClaudeCli
    if ($claude) {
        $get = Invoke-Native $claude @('mcp', 'get', $ServerName)
        $get.Out -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { Say "mcp: $_" }
        if ($get.Code -ne 0 -or $get.Out -notmatch [regex]::Escape($StagedExe)) { Warn "Claude Code MCP: '$ServerName' is not registered with $StagedExe. Run -Connect." }
    } else { Warn 'Claude Code CLI not found; cannot check the MCP registration.' }

    $plugins = Join-Path $env:USERPROFILE '.claude\plugins\installed_plugins.json'
    if ((Test-Path $plugins) -and ([IO.File]::ReadAllText($plugins) -match '"rhino-mcp@')) {
        Warn "McNeel's 'rhino-mcp' Claude Code plugin is also installed. Its tools (mcp__plugin_rhino-mcp_rhino__*) are not covered by the ask rules. Uninstall it, or add ask rules for it."
    }

    if (Test-Path $SettingsPath) {
        $s = Read-JsonFile $SettingsPath
        if (-not $s.Ok) { Warn "$SettingsPath is not valid JSON ($($s.Error))." }
        else {
            $ask = Get-AskRules $s.Obj
            foreach ($rule in $AskList) {
                if ($ask -contains $rule) { Say "ask rule: $rule" } else { Warn "Ask rule missing: $rule. Run -AskRules." }
            }
        }
    } else { Warn "$SettingsPath not found: no ask rules. Run -AskRules." }
    Say 'Check by hand in Rhino: run SetDotNetRuntime and make sure it says NETCore (the plugin does not load on .NET Framework).'
}

Say "Log: $LogFile"
Stop-Transcript | Out-Null
if ($script:Problems.Count -gt 0) {
    Write-Host ''
    Write-Host "[rhino-setup] Finished with $($script:Problems.Count) problem(s):" -ForegroundColor Yellow
    $script:Problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
    exit 6
}
Write-Host '[rhino-setup] Done. No problems found.' -ForegroundColor Green
exit 0

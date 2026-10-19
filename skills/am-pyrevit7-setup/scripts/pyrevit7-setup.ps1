<#
.SYNOPSIS
  Install pyRevit 7 per-user (no admin), point Revit at it, and connect the
  pyRevit Agent Runtime (MCP) to Claude Code.

.DESCRIPTION
  Safe to re-run. Steps (default: all, in this order):
    -Install      Download the latest per-user pyRevit installer from GitHub,
                  check its signature + SHA256, run it with /SILENT.
                  Skipped if pyRevit 7+ is already installed (use -Force to reinstall).
    -Repoint      Write per-user Revit manifests (%APPDATA%\Autodesk\Revit\Addins\<year>)
                  that load pyRevit 7, overriding an admin-owned machine-wide 6.x install.
    -EnableAgent  Turn on the agent host and register 'pyrevit mcp' with Claude Code.
    -Verify       Print the final state. Read-only.

  Never needs admin, never kills Revit. Re-run -Repoint after any pyRevit update
  or 'pyrevit attach': those remove per-user manifests and then fail on the
  admin-owned ones.

  Exit codes: 0 ok, 2 Revit must be closed, 3 install failed, 4 repoint failed,
  5 agent/MCP setup incomplete, 6 verify found problems.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\pyrevit7-setup.ps1
  powershell -ExecutionPolicy Bypass -File .\pyrevit7-setup.ps1 -Repoint -Verify
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Repoint,
    [switch]$EnableAgent,
    [switch]$Verify,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if (-not ($Install -or $Repoint -or $EnableAgent -or $Verify)) {
    $Install = $true; $Repoint = $true; $EnableAgent = $true; $Verify = $true
}

$Stamp     = Get-Date -Format 'yyyyMMdd-HHmmss'
$WorkDir   = Join-Path $env:TEMP "pyrevit7-setup\$Stamp"
$BackupDir = Join-Path $WorkDir 'backup'
New-Item -ItemType Directory -Force $WorkDir | Out-Null
$LogFile   = Join-Path $WorkDir 'setup.log'
Start-Transcript -Path $LogFile -Append | Out-Null

$Py7Root   = Join-Path $env:APPDATA 'pyRevit-Master'
$Py7       = Join-Path $Py7Root 'bin\pyrevit.exe'
$MachineAddins = 'C:\ProgramData\Autodesk\Revit\Addins'
$UserAddins    = Join-Path $env:APPDATA 'Autodesk\Revit\Addins'
$script:Problems = New-Object System.Collections.Generic.List[string]

# Shared archi-magic log (scripts\lib\am-log.ps1 at the plugin root). Optional: the standalone kit
# has no plugin root, so a missing helper means "no shared log", never a behavior change.
$script:AmStep = 'start'
$amLogPath = Join-Path $PSScriptRoot '..\..\..\scripts\lib\am-log.ps1'
if (Test-Path -LiteralPath $amLogPath) {
    try { . $amLogPath } catch { Write-Warning "archi-magic log helper not loaded: $($_.Exception.Message)" }
} else { Write-Verbose "archi-magic log helper not found at $amLogPath; shared log is off." }
if (-not (Get-Command Write-AmLog -ErrorAction SilentlyContinue)) { function Write-AmLog { } }
function AmLog($level, $msg, $code) {
    if ($null -ne $code) { Write-AmLog -Skill 'am-pyrevit7-setup' -Step $script:AmStep -Level $level -Message $msg -ExitCode $code }
    else { Write-AmLog -Skill 'am-pyrevit7-setup' -Step $script:AmStep -Level $level -Message $msg }
}

function Say($msg)  { Write-Host "[pyrevit7] $msg" }
function Warn($msg) { Write-Host "[pyrevit7] WARNING: $msg" -ForegroundColor Yellow; $script:Problems.Add($msg); AmLog 'warn' $msg $null }
function Fail($code, $msg) {
    Write-Host "[pyrevit7] FAILED: $msg" -ForegroundColor Red
    AmLog 'error' $msg $code
    Say "Log: $LogFile"
    Stop-Transcript | Out-Null
    exit $code
}

function Get-Py7Version {
    if (-not (Test-Path $Py7)) { return $null }
    $out = (& $Py7 --version 2>&1 | Out-String)
    $m = [regex]::Match($out, 'v(\d+)\.(\d+)\.(\d+)')
    if ($m.Success) { return [version]("{0}.{1}.{2}" -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value) }
    return $null
}

function Test-RevitRunning { return [bool](Get-Process Revit -ErrorAction SilentlyContinue) }

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

Say "Log file: $LogFile"
AmLog 'info' ("Setup started. Install={0} Repoint={1} EnableAgent={2} Verify={3} Force={4}" -f [bool]$Install, [bool]$Repoint, [bool]$EnableAgent, [bool]$Verify, [bool]$Force) $null

# ---------------------------------------------------------------- Install
if ($Install) {
    $script:AmStep = 'install'; AmLog 'info' 'Install step started.' $null
    Say '== Install =='
    $ver = Get-Py7Version
    if ($ver -and $ver.Major -ge 7 -and -not $Force) {
        Say "pyRevit $ver is already installed per-user at $Py7Root. Skipping install (use -Force to reinstall)."
    } else {
        if (Test-RevitRunning) { Fail 2 'Revit is running. Save your work, close Revit, and run this again.' }

        $rel = Invoke-RestMethod 'https://api.github.com/repos/pyrevitlabs/pyRevit/releases/latest' -Headers @{ 'User-Agent' = 'pyrevit7-setup' }
        $asset = @($rel.assets | Where-Object { $_.name -match '^pyRevit_[\d\.]+_signed\.exe$' })
        if ($asset.Count -ne 1) { Fail 3 "Expected exactly one per-user installer in release $($rel.tag_name), found $($asset.Count)." }
        $asset = $asset[0]
        Say "Latest release: $($rel.tag_name) -> $($asset.name) ($([math]::Round($asset.size/1MB,1)) MB)"

        $dl = Join-Path $WorkDir 'download'
        New-Item -ItemType Directory -Force $dl | Out-Null
        $exe = Join-Path $dl $asset.name
        Invoke-WebRequest $asset.browser_download_url -OutFile $exe -UseBasicParsing

        $sig = Get-AuthenticodeSignature $exe
        if ($sig.Status -ne 'Valid') { Fail 3 "Installer signature is '$($sig.Status)', not Valid. Not running it." }
        Say "Signature: Valid ($($sig.SignerCertificate.Subject))"
        if ($asset.digest -match '^sha256:([0-9a-fA-F]{64})$') {
            $hash = (Get-FileHash $exe -Algorithm SHA256).Hash
            if ($hash -ne $Matches[1].ToUpper()) { Fail 3 "SHA256 mismatch: got $hash, GitHub says $($Matches[1])." }
            Say 'SHA256 matches GitHub.'
        }

        # Do NOT pass /LOG. With /LOG this installer (Inno Setup 6.7.1) crashes intermittently at
        # startup ("Access violation ... ucrtbase.dll", exit 1); measured 2026-10-19: ~25 crashes
        # with /LOG, 5/5 clean installs of the same file without it.
        # The installer also runs 'pyrevit attach' itself, which fails silently when an admin-owned
        # machine-wide manifest exists and may delete a per-user manifest. -Repoint fixes that.
        $ok = $false
        foreach ($attempt in 1, 2) {
            Say "Running installer (attempt $attempt, ~20s)..."
            $p = Start-Process $exe -ArgumentList '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
            if ($p.ExitCode -eq 0) { $ok = $true; break }
            Warn "Installer exit code $($p.ExitCode)."
            Start-Sleep -Seconds 5
        }
        if (-not $ok) { Fail 3 "Installer failed twice. Double-click $exe yourself (no admin needed), then run this script again." }
        $ver = Get-Py7Version
        if (-not $ver -or $ver.Major -lt 7) { Fail 3 "After install, $Py7 does not report version 7+." }
        Say "Installed pyRevit $ver"
    }
    AmLog 'info' 'Install step finished.' $null
}

# ---------------------------------------------------------------- Repoint
if ($Repoint) {
    $script:AmStep = 'repoint'; AmLog 'info' 'Repoint step started.' $null
    Say '== Repoint Revit to pyRevit 7 =='
    if (-not (Test-Path $Py7)) { Fail 4 "pyRevit 7 not found at $Py7. Run with -Install first." }
    if (Test-RevitRunning) { Say 'Revit is running: changes apply the next time Revit starts.' }

    $machine = @(Get-ChildItem (Join-Path $MachineAddins '*\pyRevit*.addin') -ErrorAction SilentlyContinue)
    if ($machine.Count -eq 0) {
        Say 'No machine-wide pyRevit manifests found. Using the normal attach.'
        & $Py7 attach master default --installed
        if ($LASTEXITCODE -ne 0) { Warn "pyrevit attach exited $LASTEXITCODE." }
    } else {
        foreach ($src in $machine) {
            $year = $src.Directory.Name
            $xml  = [IO.File]::ReadAllText($src.FullName)
            $m    = [regex]::Match($xml, '<Assembly>\s*(.*?)\\bin\\')
            if (-not $m.Success) { Warn "$year : could not read <Assembly> in $($src.FullName). Skipped."; continue }
            $oldRoot = $m.Groups[1].Value
            $out = $xml.Replace($oldRoot, $Py7Root.TrimEnd('\'))
            $asm = [regex]::Match($out, '<Assembly>\s*(.*?)\s*</Assembly>').Groups[1].Value
            if (-not (Test-Path $asm)) { Warn "$year : pyRevit 7 loader not found at $asm. Skipped (this Revit year may be unsupported)."; continue }

            $dstDir = Join-Path $UserAddins $year
            $dst    = Join-Path $dstDir $src.Name
            New-Item -ItemType Directory -Force $dstDir | Out-Null
            if (Test-Path $dst) {
                New-Item -ItemType Directory -Force (Join-Path $BackupDir $year) | Out-Null
                Copy-Item $dst (Join-Path $BackupDir $year) -Force
            }
            [IO.File]::WriteAllText($dst, $out, (New-Object Text.UTF8Encoding $false))
            Say "$year : $dst -> $asm"
        }
        if (Test-Path $BackupDir) { Say "Previous per-user manifests backed up to $BackupDir" }
    }
    AmLog 'info' 'Repoint step finished.' $null
}

# ---------------------------------------------------------------- EnableAgent
if ($EnableAgent) {
    $script:AmStep = 'enable-agent'; AmLog 'info' 'EnableAgent step started.' $null
    Say '== Agent Runtime + Claude Code MCP =='
    if (-not (Test-Path $Py7)) { Fail 5 "pyRevit 7 not found at $Py7. Run with -Install first." }

    & $Py7 configs agent enable | Out-Host
    $policy = (& $Py7 configs agent policy 2>&1 | Out-String).Trim()
    Say $policy
    if ($policy -notmatch '\bask\b') { Warn "Agent policy is not 'ask'. Recommended: & `"$Py7`" configs agent policy ask" }

    $claude = Find-ClaudeCli
    if (-not $claude) {
        Warn "Claude Code CLI not found. Open Claude Code once, then re-run with -EnableAgent. Or add it manually: claude mcp add pyrevit -s user -- `"$Py7`" mcp"
    } else {
        Say "Claude Code CLI: $claude"
        # 'pyrevit mcp install claude' shells out to 'claude', so make sure it is on PATH for this process.
        $env:PATH = (Split-Path $claude) + ';' + $env:PATH
        $existing = (& $claude mcp get pyrevit 2>&1 | Out-String)
        if ($existing -match [regex]::Escape($Py7)) {
            Say 'pyrevit MCP server already registered with the full pyRevit 7 path.'
        } else {
            if ($existing -match 'Scope:') {
                Say 'Replacing an existing pyrevit MCP registration that does not use the pyRevit 7 path.'
                & $claude mcp remove pyrevit -s user 2>&1 | Out-Host
            }
            & $Py7 mcp install claude 2>&1 | Out-Host
            $existing = (& $claude mcp get pyrevit 2>&1 | Out-String)
            if ($existing -notmatch [regex]::Escape($Py7)) {
                Say 'pyrevit mcp install did not register the full path; adding it directly.'
                & $claude mcp remove pyrevit -s user 2>&1 | Out-Null
                & $claude mcp add pyrevit -s user -- "$Py7" mcp 2>&1 | Out-Host
                $existing = (& $claude mcp get pyrevit 2>&1 | Out-String)
            }
            if ($existing -notmatch [regex]::Escape($Py7)) { Warn 'Could not register the pyrevit MCP server with Claude Code.' }
            else { Say 'pyrevit MCP server registered with Claude Code (user scope).' }
        }
    }
    if (Test-RevitRunning) { Say 'Revit is running: restart Revit (or pyRevit > Reload) so it picks up the agent setting.' }
    AmLog 'info' 'EnableAgent step finished.' $null
}

# ---------------------------------------------------------------- Verify
if ($Verify) {
    $script:AmStep = 'verify'; AmLog 'info' 'Verify step started.' $null
    Say '== Verify =='
    $ver = Get-Py7Version
    if ($ver -and $ver.Major -ge 7) { Say "pyRevit (per-user): $ver" } else { Warn "pyRevit 7 not installed at $Py7" }

    $userManifests = @(Get-ChildItem (Join-Path $UserAddins '*\pyRevit*.addin') -ErrorAction SilentlyContinue)
    $machineYears  = @(Get-ChildItem (Join-Path $MachineAddins '*\pyRevit*.addin') -ErrorAction SilentlyContinue | ForEach-Object { $_.Directory.Name })
    foreach ($f in $userManifests) {
        $asm = [regex]::Match([IO.File]::ReadAllText($f.FullName), '<Assembly>\s*(.*?)\s*</Assembly>').Groups[1].Value
        $isPy7 = $asm.StartsWith($Py7Root, [StringComparison]::OrdinalIgnoreCase)
        $state = if ((Test-Path $asm) -and $isPy7) { 'OK' } else { 'BAD' }
        Say ("Revit {0}: {1}  {2}" -f $f.Directory.Name, $state, $asm)
        if ($state -eq 'BAD') { Warn "Revit $($f.Directory.Name) manifest does not point at an existing pyRevit 7 loader." }
    }
    foreach ($y in $machineYears) {
        if (-not ($userManifests | Where-Object { $_.Directory.Name -eq $y })) {
            Warn "Revit $y has a machine-wide pyRevit manifest but no per-user override: it will still load the old version. Run -Repoint."
        }
    }

    if (Test-Path $Py7) {
        $agent = (& $Py7 agent status 2>&1 | Out-String).Trim()
        $agent -split "`r?`n" | ForEach-Object { Say "agent: $_" }
        if ($agent -notmatch 'Agent host: enabled') { Warn 'Agent host is not enabled. Run -EnableAgent.' }
        if ($agent -notmatch 'responding') {
            Say 'No Revit is connected yet. To finish: open Revit (restart it if it was already open), OPEN A MODEL (an Autodesk sample such as Snowdon Towers is fine), then run this script with -Verify again.'
        }
    }

    $claude = Find-ClaudeCli
    if ($claude) {
        $reg = (& $claude mcp get pyrevit 2>&1 | Out-String)
        if ($reg -match [regex]::Escape($Py7)) { Say 'Claude Code MCP: pyrevit registered with the pyRevit 7 path.' }
        else { Warn 'Claude Code MCP: pyrevit is not registered with the pyRevit 7 path. Run -EnableAgent.' }
    } else { Warn 'Claude Code CLI not found; cannot check the MCP registration.' }
    AmLog 'info' 'Verify step finished.' $null
}

Say "Log: $LogFile"
$script:AmStep = 'end'
if ($script:Problems.Count -gt 0) { AmLog 'warn' "Setup finished with $($script:Problems.Count) problem(s)." 6 } else { AmLog 'info' 'Setup finished. No problems found.' 0 }
Stop-Transcript | Out-Null
if ($script:Problems.Count -gt 0) {
    Write-Host ''
    Write-Host "[pyrevit7] Finished with $($script:Problems.Count) problem(s):" -ForegroundColor Yellow
    $script:Problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
    exit 6
}
Write-Host '[pyrevit7] Done. No problems found.' -ForegroundColor Green
exit 0

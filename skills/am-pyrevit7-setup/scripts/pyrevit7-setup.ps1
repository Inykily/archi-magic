<#
.SYNOPSIS
  Install pyRevit 7 per-user (no admin), point Revit at it, and connect the
  pyRevit Agent Runtime (MCP) to Claude Code. -Undo reverses a previous run.

.DESCRIPTION
  Safe to re-run. Steps (default: all, in this order):
    -Install      Download the latest per-user pyRevit installer from GitHub,
                  check its signature + SHA256, run it with /SILENT.
                  Skipped if pyRevit 7+ is already installed (use -Force to reinstall).
    -Repoint      Write per-user Revit manifests (%APPDATA%\Autodesk\Revit\Addins\<year>)
                  that load pyRevit 7, overriding an admin-owned machine-wide 6.x install.
                  The per-user manifest is pyRevit7.addin: another file name than the
                  machine-wide pyRevit.addin, and the same AddInId (issue #258). Other
                  per-user pyRevit*.addin files of that year are removed (byte backup in
                  the undo journal), so Revit sees one per-user pyRevit loader per year.
                  A year installed after setup (no machine-wide manifest) gets a
                  per-user attach instead, so it is not silently skipped.
    -EnableAgent  Turn on the agent host, set the agent policy to 'ask' (or the
                  -Policy value), and register 'pyrevit mcp' with Claude Code.
    -Verify       Print the final state. Read-only. A policy other than 'ask' or
                  'readonly' is a problem (exit 6).

  -Policy ask|readonly  Policy that -EnableAgent sets. Default 'ask': every model
                  change needs Keep/Discard in Revit. 'readonly' blocks all changes.
                  'auto' (changes without approval) is never set by this script.

  Backups and undo journal: every run that changes something writes
    %LOCALAPPDATA%\archi-magic\backups\pyrevit7-setup\<timestamp>\journal.json
  with the per-user manifests it created, replaced or deleted (and a byte copy of each
  original under backup\), the MCP registration it replaced or added, and the previous
  agent enabled state and policy. The log stays in %TEMP%\pyrevit7-setup\<timestamp>\.

    -Undo [-Stamp <timestamp>]  Reverse the latest run that is not undone yet (or the
                  given run): restore or delete the per-user manifests, restore the
                  previous MCP registration (or remove the one the run added), and
                  restore the previous agent enabled state and policy. A manifest that
                  changed after the run is skipped (use -Force to restore it anyway).
                  Undo does not uninstall pyRevit 7.

  Installer trust: the installer runs only when (1) GitHub gives a SHA256 digest
  and the file matches it, (2) the Authenticode signature is Valid, and (3) the
  signer is the known pyRevit signer (subject CN/O + Microsoft ID Verified issuer).

  Never needs admin, never kills Revit. Re-run -Repoint after any pyRevit update
  or 'pyrevit attach': those remove per-user manifests and then fail on the
  admin-owned ones. When Revit is running, manifest changes apply at the next start.

  Exit codes: 0 ok, 1 unexpected error (see log), 2 Revit must be closed,
  3 install failed, 4 repoint failed, 5 agent/MCP setup incomplete,
  6 verify found problems, 7 nothing to undo (no journal, or already undone),
  8 undo finished with problems (some items skipped or failed).

  Test parameters (-UserAddinsRoot, -MachineAddinsRoot, -RevitInstallRoot, -Py7Root,
  -Py7Exe, -ClaudeCli, -BackupRoot) point the script at other folders and programs.
  Defaults are the real ones.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\pyrevit7-setup.ps1
  powershell -ExecutionPolicy Bypass -File .\pyrevit7-setup.ps1 -Repoint -Verify
  powershell -ExecutionPolicy Bypass -File .\pyrevit7-setup.ps1 -EnableAgent -Policy readonly
  powershell -ExecutionPolicy Bypass -File .\pyrevit7-setup.ps1 -Undo
  powershell -ExecutionPolicy Bypass -File .\pyrevit7-setup.ps1 -Undo -Stamp 20261020-101500
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Repoint,
    [switch]$EnableAgent,
    [switch]$Verify,
    [switch]$Force,
    [ValidateSet('ask', 'readonly')][string]$Policy = 'ask',
    [switch]$Undo,
    [string]$Stamp = '',
    [string]$UserAddinsRoot = (Join-Path $env:APPDATA 'Autodesk\Revit\Addins'),
    [string]$MachineAddinsRoot = 'C:\ProgramData\Autodesk\Revit\Addins',
    [string]$RevitInstallRoot = 'C:\Program Files\Autodesk',
    [string]$Py7Root = (Join-Path $env:APPDATA 'pyRevit-Master'),
    [string]$Py7Exe = '',
    [string]$ClaudeCli = '',
    [string]$BackupRoot = (Join-Path $env:LOCALAPPDATA 'archi-magic\backups\pyrevit7-setup')
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($Undo -and ($Install -or $Repoint -or $EnableAgent -or $Verify)) {
    Write-Host '[pyrevit7] FAILED: -Undo cannot be combined with -Install, -Repoint, -EnableAgent or -Verify.' -ForegroundColor Red
    exit 1
}
if ($Stamp -and -not $Undo) {
    Write-Host '[pyrevit7] FAILED: -Stamp is used only with -Undo.' -ForegroundColor Red
    exit 1
}
if (-not $Undo -and -not ($Install -or $Repoint -or $EnableAgent -or $Verify)) {
    $Install = $true; $Repoint = $true; $EnableAgent = $true; $Verify = $true
}

$RunStamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$WorkDir   = Join-Path $env:TEMP ("pyrevit7-setup\$RunStamp" + $(if ($Undo) { '-undo' } else { '' }))
New-Item -ItemType Directory -Force $WorkDir | Out-Null
$LogFile   = Join-Path $WorkDir 'setup.log'
Start-Transcript -Path $LogFile -Append | Out-Null

# Durable backups + undo journal (not %TEMP%, which cleanup tools empty).
$JournalDir  = Join-Path $BackupRoot $RunStamp
if (-not $Undo) {
    # Two runs in the same second must not share (and overwrite) one backup folder.
    $baseStamp = $RunStamp; $n = 2
    while (Test-Path -LiteralPath $JournalDir) { $RunStamp = "$baseStamp-$n"; $JournalDir = Join-Path $BackupRoot $RunStamp; $n++ }
}
$BackupDir   = Join-Path $JournalDir 'backup'
$JournalPath = Join-Path $JournalDir 'journal.json'

$Py7       = if ($Py7Exe) { $Py7Exe } else { Join-Path $Py7Root 'bin\pyrevit.exe' }
$MachineAddins = $MachineAddinsRoot
$UserAddins    = $UserAddinsRoot
# Per-user manifest name (issue #258). Seen on Revit 2026.4 with an IT pyRevit 6.4 for all users:
#  - same file name + same AddInId as the machine-wide pyRevit.addin: the journal said
#    "The addin file -pyRevit.addin- in all user folder is duplicated", and Revit loaded NO pyRevit;
#  - another file name + same AddInId: pyRevit 7 (per-user) loaded, and Revit refused the
#    machine-wide 6.4 with a "Duplicated AddInId" dialog.
# A new AddInId would make Revit load both pyRevit versions in one session, so the AddInId stays.
$UserManifestName = 'pyRevit7.addin'
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

function Info($msg) { Write-Host "[pyrevit7] $msg"; AmLog 'info' $msg $null }
function Say($msg)  { Write-Host "[pyrevit7] $msg" }
function Warn($msg) { Write-Host "[pyrevit7] WARNING: $msg" -ForegroundColor Yellow; $script:Problems.Add($msg); AmLog 'warn' $msg $null }
function Fail($code, $msg) {
    Complete-RepointJournal
    Write-Host "[pyrevit7] FAILED: $msg" -ForegroundColor Red
    AmLog 'error' $msg $code
    Say "Log: $LogFile"
    Stop-Transcript | Out-Null
    exit $code
}

function Get-Py7Version {
    if (-not (Test-Path $Py7)) { return $null }
    $out = (Invoke-Cli $Py7 @('--version') | Out-String)
    $m = [regex]::Match($out, 'v(\d+)\.(\d+)\.(\d+)')
    if ($m.Success) { return [version]("{0}.{1}.{2}" -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value) }
    return $null
}

function Test-RevitRunning { return [bool](Get-Process Revit -ErrorAction SilentlyContinue) }

function Find-ClaudeCli {
    if ($ClaudeCli) { if (Test-Path -LiteralPath $ClaudeCli) { return $ClaudeCli } else { return $null } }
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

# ---------------------------------------------------------------- undo journal
$script:Journal = [ordered]@{
    version = 1; stamp = $RunStamp; startedAt = (Get-Date).ToUniversalTime().ToString('o'); undoneAt = $null
    manifests = @(); createdDirs = @(); mcp = $null; agent = $null
}
function Get-Sha256([string]$path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
function Save-Journal([string]$path = $JournalPath, $data = $script:Journal) {
    # Write a temp file, then swap it in, so a crash never leaves a half-written journal.
    $dir = Split-Path $path
    New-Item -ItemType Directory -Force $dir | Out-Null
    $tmp = "$path.tmp"
    [IO.File]::WriteAllText($tmp, ($data | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $tmp -Destination $path -Force
    if (-not (Test-Path -LiteralPath $path)) { throw "Could not write the undo journal $path." }
}

# Repoint journal: snapshot every per-user pyRevit manifest (byte copy) before the step, then diff after it.
$script:RepointSnap = $null
function Get-UserManifestMap {
    $map = @{}
    foreach ($f in @(Get-ChildItem (Join-Path $UserAddins '*\pyRevit*.addin') -ErrorAction SilentlyContinue)) { $map[$f.FullName] = Get-Sha256 $f.FullName }
    return $map
}
function Start-RepointJournal {
    $files = Get-UserManifestMap
    $dirs = @(Get-ChildItem -LiteralPath $UserAddins -Directory -ErrorAction SilentlyContinue | ForEach-Object FullName)
    $backups = @{}
    foreach ($p in $files.Keys) {
        $year = Split-Path (Split-Path $p) -Leaf
        $bdir = Join-Path $BackupDir $year
        New-Item -ItemType Directory -Force $bdir | Out-Null
        $b = Join-Path $bdir (Split-Path $p -Leaf)
        Copy-Item -LiteralPath $p -Destination $b -Force    # byte copy, never a text round trip
        $backups[$p] = $b
    }
    $script:RepointSnap = @{ Files = $files; Dirs = $dirs; Backups = $backups; RootExisted = (Test-Path -LiteralPath $UserAddins) }
}
function Complete-RepointJournal {
    if (-not $script:RepointSnap) { return }
    $snap = $script:RepointSnap; $script:RepointSnap = $null
    $after = Get-UserManifestMap
    $entries = New-Object System.Collections.Generic.List[object]
    foreach ($p in @(@($snap.Files.Keys) + @($after.Keys) | Select-Object -Unique)) {
        $was = $snap.Files[$p]; $now = $after[$p]
        if ($was -and $now -and $was -eq $now) { continue }
        if ($was -and $now) { $entries.Add([ordered]@{ path = $p; action = 'replaced'; backup = $snap.Backups[$p]; backupSha256 = $was; writtenSha256 = $now }) }
        elseif ($now) { $entries.Add([ordered]@{ path = $p; action = 'created'; backup = $null; backupSha256 = $null; writtenSha256 = $now }) }
        else { $entries.Add([ordered]@{ path = $p; action = 'deleted'; backup = $snap.Backups[$p]; backupSha256 = $was; writtenSha256 = $null }) }
    }
    $newDirs = @(Get-ChildItem -LiteralPath $UserAddins -Directory -ErrorAction SilentlyContinue | ForEach-Object FullName | Where-Object { $snap.Dirs -notcontains $_ })
    # Unchanged files need no backup: drop their copies so a backup always means "this run changed it".
    foreach ($p in $snap.Backups.Keys) {
        if (-not ($entries | Where-Object { $_.path -eq $p })) { Remove-Item -LiteralPath $snap.Backups[$p] -Force -ErrorAction SilentlyContinue }
    }
    if ($entries.Count -gt 0 -or $newDirs.Count -gt 0) {
        $script:Journal['manifests'] = @($script:Journal['manifests']) + @($entries.ToArray())
        $script:Journal['createdDirs'] = @($script:Journal['createdDirs']) + @($newDirs)
        Save-Journal
    }
    if (Test-Path -LiteralPath $BackupDir) {
        Get-ChildItem -LiteralPath $BackupDir -Directory -ErrorAction SilentlyContinue | Where-Object { -not (Get-ChildItem -LiteralPath $_.FullName) } | Remove-Item -Force -ErrorAction SilentlyContinue
        if (-not (Get-ChildItem -LiteralPath $BackupDir -ErrorAction SilentlyContinue)) { Remove-Item -LiteralPath $BackupDir -Force -ErrorAction SilentlyContinue }
    }
    if (-not (Test-Path -LiteralPath $JournalPath) -and (Test-Path -LiteralPath $JournalDir) -and -not (Get-ChildItem -LiteralPath $JournalDir)) {
        Remove-Item -LiteralPath $JournalDir -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Cli([string]$exe, [string[]]$argv) {
    # Runs a native CLI (claude, pyrevit) and emits its stdout and stderr as plain text lines.
    # 'claude mcp get/remove' on a missing server writes to stderr and exits 1. With the script-wide
    # EAP 'Stop', Windows PowerShell 5.1 turns a redirected stderr line into a terminating error,
    # so the preference is 'Continue' here only. $LASTEXITCODE keeps the exit code for the caller.
    $ErrorActionPreference = 'Continue'
    & $exe @argv 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { [string]$_ }
    }
}

function Get-NormalPath([string]$path) {
    # One spelling per file: 'C:\x\AppData\Roaming/pyRevit-Master/bin/pyrevit.exe' and the same path
    # with backslashes must compare equal. GetFullPath throws on an empty or odd string: keep it raw then.
    $p = ([string]$path).Trim().Trim('"')
    try { return [IO.Path]::GetFullPath($p) } catch { return $p }
}
# Installed Revit years: the "Revit 20*" folders under the Revit install root.
# -RevitInstallRoot is the test seam: tests point it at a temp folder. A Revit
# installed to a custom path outside it is a known gap, not an attach target.
function Get-InstalledRevitYears([string]$root) {
    $years = @()
    foreach ($d in @(Get-ChildItem -LiteralPath $root -Directory -Filter 'Revit 20*' -ErrorAction SilentlyContinue)) {
        $y = ($d.Name -replace '\D', '')
        if ($y -match '^\d{4}$') { $years += $y }
    }
    return @($years | Sort-Object -Unique)
}

# One field of a Revit add-in manifest (Assembly, AddInId). AddInId comes back upper case, no braces.
function Get-ManifestField([string]$path, [string]$tag) {
    $v = [regex]::Match([IO.File]::ReadAllText($path), "<$tag>\s*(.*?)\s*</$tag>").Groups[1].Value
    if ($tag -eq 'AddInId') { $v = $v.Trim('{', '}', ' ').ToUpperInvariant() }
    return $v
}
function Test-Py7Manifest([string]$path) {
    $asm = Get-ManifestField $path 'Assembly'
    return [bool]($asm -and $asm.StartsWith($Py7Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $asm))
}

# Keep one per-user pyRevit manifest for a Revit year and remove the others (issue #258: two per-user
# loaders, or one with the machine-wide file name, left Revit with the old pyRevit or none).
# Start-RepointJournal made a byte copy of each one that existed before this run, and
# Complete-RepointJournal records the removal, so -Undo restores it. A file that this run created
# (for example the installer's own attach) has no backup and needs none: undo returns to the state
# before the run, when that file did not exist.
function Remove-ExtraUserManifests([string]$year, [string]$keepPath) {
    foreach ($f in @(Get-ChildItem (Join-Path (Join-Path $UserAddins $year) 'pyRevit*.addin') -ErrorAction SilentlyContinue)) {
        if ($f.FullName -ieq $keepPath) { continue }
        if ($script:RepointSnap -and $script:RepointSnap.Files.ContainsKey($f.FullName)) {
            $b = $script:RepointSnap.Backups[$f.FullName]
            if (-not $b -or -not (Test-Path -LiteralPath $b)) { Warn "Revit $year : $($f.FullName) has no backup copy, so it was not removed. Revit can load only one pyRevit: remove it by hand."; continue }
        }
        Remove-Item -LiteralPath $f.FullName -Force
        Say "Revit $year : removed the extra per-user manifest $($f.Name) (the undo journal keeps a copy). Revit now sees one per-user pyRevit: $(Split-Path $keepPath -Leaf)"
    }
}

function Test-SamePath([string]$a, [string]$b) {
    if (-not $a -or -not $b) { return $false }
    return ((Get-NormalPath $a) -ieq (Get-NormalPath $b))
}
function Test-McpUsesPy7([string]$claude) {
    # True when 'claude mcp get pyrevit' names the pyRevit 7 exe (any slash style).
    $reg = Get-McpRegistration $claude
    return [bool]($reg -and (Test-SamePath $reg.command $Py7))
}

function Get-McpRegistration([string]$claude) {
    # Parses 'claude mcp get pyrevit'. Returns $null when no server has that name.
    $out = (Invoke-Cli $claude @('mcp', 'get', 'pyrevit') | Out-String)
    if ($out -notmatch '(?m)^\s*Scope:') { return $null }
    $scopeText = [regex]::Match($out, '(?m)^\s*Scope:\s*(.+?)\s*$').Groups[1].Value
    $scope = if ($scopeText -match '^User') { 'user' } elseif ($scopeText -match '^Project') { 'project' } elseif ($scopeText -match '^Local') { 'local' } else { $scopeText }
    $envList = @()
    $inEnv = $false
    foreach ($line in ($out -split "`r?`n")) {
        if ($line -match '^\s*Environment:') { $inEnv = $true; continue }
        if ($inEnv) {
            if ($line -match '^\s{3,}(\w+)=(.*)$') { $envList += "$($Matches[1])=$($Matches[2])" } else { $inEnv = $false }
        }
    }
    return [ordered]@{
        scope   = $scope
        type    = [regex]::Match($out, '(?m)^\s*Type:\s*(.+?)\s*$').Groups[1].Value
        command = [regex]::Match($out, '(?m)^\s*Command:\s*(.+?)\s*$').Groups[1].Value
        args    = [regex]::Match($out, '(?m)^\s*Args:\s*(.*?)\s*$').Groups[1].Value
        env     = $envList
        raw     = $out.Trim()
    }
}

# Known pyRevit installer signer (read 2026-10-20 from pyRevit_7.0.0.26278_signed.exe).
#   Subject: CN=Jean-Marc Couffin, O=Jean-Marc Couffin, L=Zlin, S=Zlinsky (with accents), C=CZ
#   Issuer : CN=Microsoft ID Verified CS AOC CA 03, O=Microsoft Corporation, C=US
# Microsoft's ID Verified signing service issues certificates that live about 3 days, so the
# thumbprint changes with almost every release. The hard pin is therefore subject CN + O + C and
# the Microsoft ID Verified issuer. Known thumbprints are recorded; a new one is reported, not refused.
$SignerCN          = 'Jean-Marc Couffin'
$SignerO           = 'Jean-Marc Couffin'
$SignerC           = 'CZ'
$SignerIssuerRegex = '^CN=Microsoft ID Verified CS (AOC|EOC) CA \d+, O=Microsoft Corporation, C=US$'
$KnownThumbprints  = @('D20345056E74D1858EEB0D336472C5B462CE0120')

function Get-DnPart([string]$dn, [string]$key) {
    $m = [regex]::Match($dn, '(?:^|,\s*)' + $key + '=([^,]+)')
    if ($m.Success) { return $m.Groups[1].Value.Trim() } else { return $null }
}

function Test-InstallerTrust([string]$Path, $Digest) {
    # Returns a list of failure reasons. An empty list means the installer may run.
    $why = New-Object System.Collections.Generic.List[string]
    if (-not ($Digest -is [string]) -or $Digest -notmatch '^sha256:([0-9a-fA-F]{64})$') {
        $why.Add('GitHub did not give a SHA256 checksum for this file, so its content cannot be confirmed.')
    } else {
        $want = $Matches[1].ToUpperInvariant()
        $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
        if ($hash -ne $want) { $why.Add("The file checksum does not match GitHub (got $hash, GitHub says $want). The download is damaged or changed.") }
    }
    $sig = Get-AuthenticodeSignature -LiteralPath $Path
    if ($sig.Status -ne 'Valid') {
        $why.Add("The digital signature is '$($sig.Status)', not Valid.")
    } else {
        $cert = $sig.SignerCertificate
        $cn = Get-DnPart $cert.Subject 'CN'; $o = Get-DnPart $cert.Subject 'O'; $c = Get-DnPart $cert.Subject 'C'
        if ($cn -ne $SignerCN -or $o -ne $SignerO -or $c -ne $SignerC) {
            $why.Add("The signer is '$($cert.Subject)', not the known pyRevit signer (CN=$SignerCN, O=$SignerO, C=$SignerC).")
        }
        if ($cert.Issuer -notmatch $SignerIssuerRegex) {
            $why.Add("The signer certificate comes from '$($cert.Issuer)', not from Microsoft ID Verified signing.")
        }
    }
    return ,$why
}

function Get-AgentPolicy {
    # 'pyrevit configs agent policy' prints "Agent policy: ask". Returns ask|readonly|auto, or $null.
    if (-not (Test-Path $Py7)) { return $null }
    $out = (Invoke-Cli $Py7 @('configs', 'agent', 'policy') | Out-String)
    $m = [regex]::Match($out, 'Agent policy:\s*(\w+)')
    if ($m.Success) { return $m.Groups[1].Value.ToLowerInvariant() }
    return $null
}

function Get-AgentEnabled {
    # 'pyrevit configs agent' prints "Agent host is Enabled" or "... Disabled". Returns $true, $false or $null.
    if (-not (Test-Path $Py7)) { return $null }
    $out = (Invoke-Cli $Py7 @('configs', 'agent') | Out-String)
    if ($out -match '\bDisabled\b') { return $false }
    if ($out -match '\bEnabled\b') { return $true }
    return $null
}

function Get-NetFailureText($err) {
    # Plain words for a failed call to GitHub. Names the two usual office causes.
    $status = $null
    try { $status = [int]$err.Exception.Response.StatusCode } catch { $status = $null }
    $why = if ($status -eq 403 -or $status -eq 429) {
        "GitHub refused the request (HTTP $status). GitHub limits each office internet address to 60 requests per hour. Wait one hour, then run this again."
    } elseif ($status) {
        "GitHub answered HTTP $status."
    } else {
        'The computer could not reach GitHub. A corporate proxy or TLS inspection can block it. Ask IT to allow api.github.com and github.com, or run this from another network.'
    }
    return "$why Details: $($err.Exception.Message)"
}

# Any error that no step handles: stop with exit 1 and show the log, not a raw stack trace.
trap {
    try { Complete-RepointJournal } catch { }
    Write-Host "[pyrevit7] FAILED: Unexpected error: $($_.Exception.Message) (script line $($_.InvocationInfo.ScriptLineNumber))" -ForegroundColor Red
    AmLog 'error' "Unexpected error: $($_.Exception.Message)" 1
    Write-Host "[pyrevit7] Log: $LogFile"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

Say "Log file: $LogFile"

# ---------------------------------------------------------------- Undo
if ($Undo) {
    $script:AmStep = 'undo'
    AmLog 'info' ("Undo started. Stamp={0} Force={1}" -f $(if ($Stamp) { $Stamp } else { 'latest' }), [bool]$Force) $null
    Say '== Undo a previous setup run =='
    $jpath = $null
    if ($Stamp) {
        $jpath = Join-Path (Join-Path $BackupRoot $Stamp) 'journal.json'
        if (-not (Test-Path -LiteralPath $jpath)) { Fail 7 "No undo journal for run $Stamp at $jpath." }
    } else {
        $cands = @(Get-ChildItem -LiteralPath $BackupRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending)
        foreach ($d in $cands) {
            $p = Join-Path $d.FullName 'journal.json'
            if (-not (Test-Path -LiteralPath $p)) { continue }
            try { $j0 = [IO.File]::ReadAllText($p) | ConvertFrom-Json } catch { continue }
            if (-not $j0.undoneAt) { $jpath = $p; break }
        }
        if (-not $jpath) { Fail 7 "No setup run to undo under $BackupRoot (none found, or all are already undone)." }
    }
    $j = [IO.File]::ReadAllText($jpath) | ConvertFrom-Json
    if ($j.undoneAt -and -not $Force) { Fail 7 "Run $($j.stamp) was already undone at $($j.undoneAt). Use -Force to undo it again." }
    Say "Undoing run $($j.stamp) (journal: $jpath)"
    if (Test-RevitRunning) { Say 'Revit is running: the manifest changes apply the next time Revit starts.' }

    # 1. Manifests, newest change first.
    $ms = @($j.manifests)
    [array]::Reverse($ms)
    foreach ($m in $ms) {
        $p = [string]$m.path
        $cur = if (Test-Path -LiteralPath $p) { Get-Sha256 $p } else { $null }
        switch ([string]$m.action) {
            'created' {
                if (-not $cur) { Say "Already gone: $p"; break }
                if ($cur -ne $m.writtenSha256 -and -not $Force) { Warn "Skipped $p : it changed after the setup run (use -Force to delete it anyway)."; break }
                Remove-Item -LiteralPath $p -Force
                Say "Deleted (the setup run created it): $p"
            }
            'replaced' {
                if (-not $m.backup -or -not (Test-Path -LiteralPath $m.backup)) { Warn "Cannot restore $p : backup $($m.backup) is missing."; break }
                if ($cur -and $cur -ne $m.writtenSha256 -and -not $Force) { Warn "Skipped $p : it changed after the setup run (use -Force to restore the backup anyway)."; break }
                New-Item -ItemType Directory -Force (Split-Path $p) | Out-Null
                Copy-Item -LiteralPath $m.backup -Destination $p -Force
                if ((Get-Sha256 $p) -ne $m.backupSha256) { Warn "Restored $p, but its checksum does not match the backup record." }
                else { Say "Restored the original: $p" }
            }
            'deleted' {
                if (-not $m.backup -or -not (Test-Path -LiteralPath $m.backup)) { Warn "Cannot restore $p : backup $($m.backup) is missing."; break }
                if ($cur -and $cur -ne $m.backupSha256 -and -not $Force) { Warn "Skipped $p : a different file is there now (use -Force to restore the backup anyway)."; break }
                New-Item -ItemType Directory -Force (Split-Path $p) | Out-Null
                Copy-Item -LiteralPath $m.backup -Destination $p -Force
                if ((Get-Sha256 $p) -ne $m.backupSha256) { Warn "Restored $p, but its checksum does not match the backup record." }
                else { Say "Restored (the setup run deleted it): $p" }
            }
            default { Warn "Unknown journal action '$($m.action)' for $p. Skipped." }
        }
    }
    foreach ($d in @($j.createdDirs)) {
        if ($d -and (Test-Path -LiteralPath $d) -and -not (Get-ChildItem -LiteralPath $d -Force)) {
            Remove-Item -LiteralPath $d -Force
            Say "Removed the empty folder the setup run created: $d"
        }
    }
    # Undo can bring back a per-user manifest with the machine-wide file name (the layout before
    # issue #258). Say so, but do not count it as an undo problem: undo did what was asked.
    foreach ($mf in @(Get-ChildItem (Join-Path $MachineAddins '*\pyRevit*.addin') -ErrorAction SilentlyContinue)) {
        $twin = Join-Path (Join-Path $UserAddins $mf.Directory.Name) $mf.Name
        if (Test-Path -LiteralPath $twin) {
            Say "Note: Revit $($mf.Directory.Name): the restored per-user $($mf.Name) has the same file name as the machine-wide manifest. On Revit 2026.4 this loaded no pyRevit. Run -Repoint to fix it again."
        }
    }

    # 2. MCP registration.
    if ($j.mcp) {
        $claude = Find-ClaudeCli
        if (-not $claude) { Warn 'Claude Code CLI not found; the MCP registration was not restored.' }
        else {
            $env:PATH = (Split-Path $claude) + ';' + $env:PATH
            if ($j.mcp.action -eq 'added') {
                Invoke-Cli $claude @('mcp', 'remove', 'pyrevit', '-s', 'user') | Out-Host
                $left = Get-McpRegistration $claude
                if ($left -and $left.scope -eq 'user') { Warn 'Could not remove the pyrevit MCP server that the setup run added.' }
                else { Say 'Removed the pyrevit MCP registration that the setup run added.' }
            } elseif ($j.mcp.action -eq 'replaced') {
                $prev = $j.mcp.previous
                if ($prev.type -and $prev.type -ne 'stdio') {
                    Warn "The previous pyrevit MCP server was type '$($prev.type)'. Restore it by hand: claude mcp add --transport $($prev.type) pyrevit $($prev.command)"
                } else {
                    Invoke-Cli $claude @('mcp', 'remove', 'pyrevit', '-s', 'user') | Out-Host
                    $argv = @('mcp', 'add', 'pyrevit', '-s', [string]$prev.scope)
                    foreach ($e in @($prev.env)) { if ($e) { $argv += @('-e', [string]$e) } }
                    $argv += '--'
                    $argv += [string]$prev.command
                    if ($prev.args) { $argv += @(([string]$prev.args) -split '\s+' | Where-Object { $_ }) }
                    Invoke-Cli $claude $argv | Out-Host
                    $now = Get-McpRegistration $claude
                    if ($now -and (Test-SamePath $now.command $prev.command)) { Say "Restored the previous pyrevit MCP registration: $($prev.command) $($prev.args)" }
                    else { Warn "Could not restore the previous pyrevit MCP registration ($($prev.command) $($prev.args))." }
                }
            }
        }
    }

    # 3. Agent enabled state and policy.
    if ($j.agent) {
        if (-not (Test-Path $Py7)) { Warn "pyRevit not found at $Py7; the agent setting was not restored." }
        else {
            if ($j.agent.wasEnabled -eq $false -and (Get-AgentEnabled) -ne $false) {
                Invoke-Cli $Py7 @('configs', 'agent', 'disable') | Out-Host
                if ((Get-AgentEnabled) -ne $false) { Warn 'Could not disable the agent host again.' } else { Say 'Agent host: disabled again (as before the setup run).' }
            }
            $prevPol = [string]$j.agent.policy
            if ($prevPol -and $prevPol -ne (Get-AgentPolicy)) {
                if ($prevPol -eq 'auto') {
                    Write-Host "[pyrevit7] WARNING: the previous agent policy was 'auto'. Model changes will run WITHOUT the Keep/Discard approval in Revit. To keep the approval, run: & `"$Py7`" configs agent policy ask" -ForegroundColor Yellow
                    AmLog 'warn' "Undo restored agent policy 'auto'." $null
                }
                Invoke-Cli $Py7 @('configs', 'agent', 'policy', $prevPol) | Out-Host
                if ((Get-AgentPolicy) -ne $prevPol) { Warn "Could not restore the agent policy '$prevPol'." } else { Say "Agent policy restored to '$prevPol'." }
            }
        }
    }

    $j | Add-Member -NotePropertyName undoneAt -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('o')) -Force
    Save-Journal -path $jpath -data $j
    Say 'Undo does not uninstall pyRevit 7. Restart Revit and start a new Claude Code session to pick up the changes.'
    Say "Log: $LogFile"
    $script:AmStep = 'end'
    Stop-Transcript | Out-Null
    if ($script:Problems.Count -gt 0) {
        AmLog 'warn' "Undo finished with $($script:Problems.Count) problem(s)." 8
        Write-Host "[pyrevit7] Undo finished with $($script:Problems.Count) problem(s):" -ForegroundColor Yellow
        $script:Problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
        exit 8
    }
    AmLog 'info' 'Undo finished. No problems found.' 0
    Write-Host '[pyrevit7] Undo done. No problems found.' -ForegroundColor Green
    exit 0
}

AmLog 'info' ("Setup started. Install={0} Repoint={1} EnableAgent={2} Verify={3} Force={4}" -f [bool]$Install, [bool]$Repoint, [bool]$EnableAgent, [bool]$Verify, [bool]$Force) $null

# Snapshot the per-user manifests before Install too: the installer runs 'pyrevit attach' itself,
# which can delete a per-user manifest. Undo must return to the state before the whole run.
if ($Install -or $Repoint) { Start-RepointJournal }

# ---------------------------------------------------------------- Install
if ($Install) {
    $script:AmStep = 'install'; AmLog 'info' 'Install step started.' $null
    Say '== Install =='
    $ver = Get-Py7Version
    if ($ver -and $ver.Major -ge 7 -and -not $Force) {
        Say "pyRevit $ver is already installed per-user at $Py7Root. Skipping install (use -Force to reinstall)."
    } else {
        if (Test-RevitRunning) { Fail 2 'Revit is running. Save your work, close Revit, and run this again.' }

        try {
            $rel = Invoke-RestMethod 'https://api.github.com/repos/pyrevitlabs/pyRevit/releases/latest' -Headers @{ 'User-Agent' = 'pyrevit7-setup' }
        } catch {
            Fail 3 ("Could not read the latest pyRevit release from GitHub. " + (Get-NetFailureText $_))
        }
        $asset = @($rel.assets | Where-Object { $_.name -match '^pyRevit_[\d\.]+_signed\.exe$' })
        if ($asset.Count -ne 1) { Fail 3 "Expected exactly one per-user installer in release $($rel.tag_name), found $($asset.Count)." }
        $asset = $asset[0]
        Say "Latest release: $($rel.tag_name) -> $($asset.name) ($([math]::Round($asset.size/1MB,1)) MB)"

        $dl = Join-Path $WorkDir 'download'
        New-Item -ItemType Directory -Force $dl | Out-Null
        $exe = Join-Path $dl $asset.name
        try {
            Invoke-WebRequest $asset.browser_download_url -OutFile $exe -UseBasicParsing
        } catch {
            Fail 3 ("Could not download the pyRevit installer. " + (Get-NetFailureText $_))
        }

        $trust = Test-InstallerTrust -Path $exe -Digest $asset.digest
        if ($trust.Count -gt 0) {
            Fail 3 ("The pyRevit installer did not pass the safety check. The script did not run it. " + ($trust -join ' ') + " Tell your BIM manager or IT. Do not run $exe yourself.")
        }
        $cert = (Get-AuthenticodeSignature -LiteralPath $exe).SignerCertificate
        Say "SHA256 matches GitHub. Signature: Valid, signer $(Get-DnPart $cert.Subject 'CN'), issuer $(Get-DnPart $cert.Issuer 'CN')."
        if ($KnownThumbprints -notcontains $cert.Thumbprint) {
            Info "New signer certificate thumbprint $($cert.Thumbprint) (subject and issuer match). Maintainers: add it to `$KnownThumbprints."
        }

        # Do NOT pass /LOG. With /LOG this installer (Inno Setup 6.7.1) crashes intermittently at
        # startup ("Access violation ... ucrtbase.dll", exit 1); measured 2026-10-19: ~25 crashes
        # with /LOG, 5/5 clean installs of the same file without it.
        # The installer also runs 'pyrevit attach' itself, which fails silently when an admin-owned
        # machine-wide manifest exists and may delete a per-user manifest. -Repoint fixes that.
        # A failed first attempt followed by a good retry is info, not a problem (it must not force exit 6).
        $ok = $false
        $failedCodes = New-Object System.Collections.Generic.List[string]
        foreach ($attempt in 1, 2) {
            Say "Running installer (attempt $attempt, ~20s)..."
            $p = Start-Process $exe -ArgumentList '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
            if ($p.ExitCode -eq 0) { $ok = $true; break }
            Say "Installer attempt $attempt stopped with exit code $($p.ExitCode)."
            $failedCodes.Add([string]$p.ExitCode)
            if ($attempt -lt 2) { Start-Sleep -Seconds 5 }
        }
        if (-not $ok) { Fail 3 "Installer failed twice (exit codes $($failedCodes -join ', ')). Double-click $exe yourself (no admin needed), then run this script again." }
        if ($failedCodes.Count -gt 0) { Info "Installer attempt 1 failed (exit code $($failedCodes[0])); the retry succeeded." }
        $ver = Get-Py7Version
        if (-not $ver -or $ver.Major -lt 7) { Fail 3 "After install, $Py7 does not report version 7+." }
        Say "Installed pyRevit $ver"
    }
    AmLog 'info' 'Install step finished.' $null
    if (-not $Repoint) { Complete-RepointJournal }
}

# ---------------------------------------------------------------- Repoint
if ($Repoint) {
    $script:AmStep = 'repoint'; AmLog 'info' 'Repoint step started.' $null
    Say '== Repoint Revit to pyRevit 7 =='
    if (-not (Test-Path $Py7)) { Fail 4 "pyRevit 7 not found at $Py7. Run with -Install first." }
    if (Test-RevitRunning) { Say 'Revit is running: changes apply the next time Revit starts.' }

    if (-not $script:RepointSnap) { Start-RepointJournal }
    $machine =@(Get-ChildItem (Join-Path $MachineAddins '*\pyRevit*.addin') -ErrorAction SilentlyContinue)
    if ($machine.Count -eq 0) {
        Say 'No machine-wide pyRevit manifests found. Using the normal attach.'
        Invoke-Cli $Py7 @('attach', 'master', 'default', '--installed') | Out-Host
        if ($LASTEXITCODE -ne 0) { Warn "pyrevit attach exited $LASTEXITCODE." }
    } else {
        # One per-user manifest per Revit year (issue #258): its own file name ($UserManifestName,
        # never the machine-wide name) and the machine-wide AddInId (the XML is copied, only the
        # install root changes). Then the other per-user pyRevit manifests of that year go.
        foreach ($g in @($machine | Group-Object { $_.Directory.Name } | Sort-Object Name)) {
            $year = $g.Name
            $srcs = @($g.Group | Sort-Object Name)
            $src  = $srcs[0]
            if ($srcs.Count -gt 1) { Say "$year : $($srcs.Count) machine-wide pyRevit manifests ($(@($srcs | ForEach-Object { $_.Name }) -join ', ')). Using $($src.Name)." }
            $xml  = [IO.File]::ReadAllText($src.FullName)
            $m    = [regex]::Match($xml, '<Assembly>\s*(.*?)\\bin\\')
            if (-not $m.Success) { Warn "$year : could not read <Assembly> in $($src.FullName). Skipped."; continue }
            $oldRoot = $m.Groups[1].Value
            $out = $xml.Replace($oldRoot, $Py7Root.TrimEnd('\'))
            $asm = [regex]::Match($out, '<Assembly>\s*(.*?)\s*</Assembly>').Groups[1].Value
            if (-not (Test-Path $asm)) { Warn "$year : pyRevit 7 loader not found at $asm. Skipped (this Revit year may be unsupported)."; continue }

            $dstName = $UserManifestName
            if (@($srcs | ForEach-Object { $_.Name }) -contains $dstName) { $dstName = 'pyRevit7-user.addin' }
            $dstDir = Join-Path $UserAddins $year
            $dst    = Join-Path $dstDir $dstName
            New-Item -ItemType Directory -Force $dstDir | Out-Null
            [IO.File]::WriteAllText($dst, $out, (New-Object Text.UTF8Encoding $false))
            Say "$year : $dst -> $asm"
            Remove-ExtraUserManifests $year $dst
        }
        # Installed Revit years with no machine-wide manifest (issue #88): the loop above
        # only visits years IT attached, so a year installed after setup was silently
        # skipped. For each such year with no per-user manifest either, attach per-user
        # (the manual fix from the issue: no --allusers, no admin). Years repointed
        # above now have a per-user manifest, so they are skipped here; a later Repoint
        # run therefore leaves an attached year untouched. The attach writes only that
        # year's folder: the issue's own fix left the neighbouring years unchanged.
        $installedYears = Get-InstalledRevitYears $RevitInstallRoot
        if ($installedYears.Count -gt 0) {
            $userYears = @(Get-ChildItem (Join-Path $UserAddins '*\pyRevit*.addin') -ErrorAction SilentlyContinue | ForEach-Object { $_.Directory.Name })
            $attachedMachineYears = @($machine | ForEach-Object { $_.Directory.Name })
            foreach ($y in $installedYears) {
                if ($attachedMachineYears -contains $y) { continue }
                if ($userYears -contains $y) { continue }
                Invoke-Cli $Py7 @('attach', 'master', 'default', $y) | Out-Host
                if ($LASTEXITCODE -ne 0) { Warn "Revit $y : per-user attach failed (exit $LASTEXITCODE); Revit starts without pyRevit for this year." }
                else { Say "Revit $y : attached per-user (no machine-wide manifest)" }
            }
        }
    }
    # A year with no machine-wide manifest and more than one per-user pyRevit manifest (for example
    # pyRevit7.addin from an earlier Repoint and pyRevit.addin from 'pyrevit attach' after IT removed
    # the machine-wide pyRevit): keep one that loads pyRevit 7, pyRevit's own pyRevit.addin first.
    $machineYears = @($machine | ForEach-Object { $_.Directory.Name } | Sort-Object -Unique)
    $multi = @(Get-ChildItem (Join-Path $UserAddins '*\pyRevit*.addin') -ErrorAction SilentlyContinue |
        Group-Object { $_.Directory.Name } | Where-Object { $_.Count -gt 1 -and $machineYears -notcontains $_.Name })
    foreach ($g in $multi) {
        $keep = @($g.Group | Where-Object { Test-Py7Manifest $_.FullName } | Sort-Object @{ Expression = { $_.Name -ine 'pyRevit.addin' } }, Name)
        if ($keep.Count -eq 0) { Warn "Revit $($g.Name) : $($g.Count) per-user pyRevit manifests and none loads pyRevit 7. Not changed."; continue }
        Remove-ExtraUserManifests $g.Name $keep[0].FullName
    }
    Complete-RepointJournal
    if (Test-Path -LiteralPath $BackupDir) { Say "Previous per-user manifests backed up to $BackupDir" }
    if (Test-Path -LiteralPath $JournalPath) { Say "Undo journal: $JournalPath (run with -Undo to reverse this run)" }
    AmLog 'info' 'Repoint step finished.' $null
}

# ---------------------------------------------------------------- EnableAgent
if ($EnableAgent) {
    $script:AmStep = 'enable-agent'; AmLog 'info' 'EnableAgent step started.' $null
    Say '== Agent Runtime + Claude Code MCP =='
    if (-not (Test-Path $Py7)) { Fail 5 "pyRevit 7 not found at $Py7. Run with -Install first." }

    $wasEnabled = Get-AgentEnabled
    $before = Get-AgentPolicy
    # Keep/Discard in Revit exists only under policy 'ask'. Set it explicitly; never leave 'auto' in place.
    # A re-run must never loosen a stricter choice: keep an existing 'readonly' unless -Policy was passed.
    if ($before -eq 'readonly' -and -not $PSBoundParameters.ContainsKey('Policy')) { $Policy = 'readonly' }
    # Journal the previous agent state only when this run changes it, so a no-op re-run never
    # becomes the "latest run" that -Undo would pick.
    if ($wasEnabled -ne $true -or $before -ne $Policy) {
        $script:Journal['agent'] = [ordered]@{ wasEnabled = $wasEnabled; policy = $before }
        Save-Journal
    }

    Invoke-Cli $Py7 @('configs', 'agent', 'enable') | Out-Host
    Invoke-Cli $Py7 @('configs', 'agent', 'policy', $Policy) | Out-Host
    $policyNow = Get-AgentPolicy
    if ($policyNow -ne $Policy) {
        Warn "Agent policy is '$policyNow', not '$Policy'. Run: & `"$Py7`" configs agent policy $Policy"
    } elseif ($before -and $before -ne $Policy) {
        Info "Agent policy changed from '$before' to '$Policy'."
    } else {
        Say "Agent policy: $policyNow"
    }

    $claude = Find-ClaudeCli
    if (-not $claude) {
        Warn "Claude Code CLI not found. Open Claude Code once, then re-run with -EnableAgent. Or add it manually: claude mcp add pyrevit -s user -- `"$Py7`" mcp"
    } else {
        Say "Claude Code CLI: $claude"
        # 'pyrevit mcp install claude' shells out to 'claude', so make sure it is on PATH for this process.
        $env:PATH = (Split-Path $claude) + ';' + $env:PATH
        $prevReg = Get-McpRegistration $claude
        if ($prevReg -and (Test-SamePath $prevReg.command $Py7)) {
            Say 'pyrevit MCP server already registered with the full pyRevit 7 path.'
        } else {
            # Journal what is replaced (only a user-scope entry is removed) or that a new one is added.
            if ($prevReg -and $prevReg.scope -eq 'user') { $script:Journal['mcp'] = [ordered]@{ action = 'replaced'; previous = $prevReg } }
            else { $script:Journal['mcp'] = [ordered]@{ action = 'added'; previous = $prevReg } }
            Save-Journal
            if ($prevReg) {
                Say 'Replacing an existing pyrevit MCP registration that does not use the pyRevit 7 path.'
                Invoke-Cli $claude @('mcp', 'remove', 'pyrevit', '-s', 'user') | Out-Host
            }
            # pyrevit shells out to claude, so its stderr can carry the same 'not found' lines.
            Invoke-Cli $Py7 @('mcp', 'install', 'claude') | Out-Host
            if (-not (Test-McpUsesPy7 $claude)) {
                Say 'pyrevit mcp install did not register the full path; adding it directly.'
                Invoke-Cli $claude @('mcp', 'remove', 'pyrevit', '-s', 'user') | Out-Null
                Invoke-Cli $claude @('mcp', 'add', 'pyrevit', '-s', 'user', '--', "$Py7", 'mcp') | Out-Host
            }
            if (-not (Test-McpUsesPy7 $claude)) { Warn 'Could not register the pyrevit MCP server with Claude Code.' }
            else { Say 'pyrevit MCP server registered with Claude Code (user scope).' }
        }
    }
    if (Test-RevitRunning) { Say 'Revit is running: restart Revit (or pyRevit > Reload) so it picks up the agent setting.' }
    if (Test-Path -LiteralPath $JournalPath) { Say "Undo journal: $JournalPath (run with -Undo to reverse this run)" }
    AmLog 'info' 'EnableAgent step finished.' $null
}

# ---------------------------------------------------------------- Verify
if ($Verify) {
    $script:AmStep = 'verify'; AmLog 'info' 'Verify step started.' $null
    Say '== Verify =='
    $ver = Get-Py7Version
    if ($ver -and $ver.Major -ge 7) { Say "pyRevit (per-user): $ver" } else { Warn "pyRevit 7 not installed at $Py7" }

    $userManifests = @(Get-ChildItem (Join-Path $UserAddins '*\pyRevit*.addin') -ErrorAction SilentlyContinue)
    $machineFiles  = @(Get-ChildItem (Join-Path $MachineAddins '*\pyRevit*.addin') -ErrorAction SilentlyContinue)
    $machineYears  = @($machineFiles | ForEach-Object { $_.Directory.Name } | Sort-Object -Unique)
    foreach ($f in $userManifests) {
        $asm = Get-ManifestField $f.FullName 'Assembly'
        $isPy7 = $asm.StartsWith($Py7Root, [StringComparison]::OrdinalIgnoreCase)
        $state = if ($asm -and (Test-Path $asm) -and $isPy7) { 'OK' } else { 'BAD' }
        Say ("Revit {0}: {1}  {2}  ({3})" -f $f.Directory.Name, $state, $asm, $f.Name)
        if ($state -eq 'BAD') { Warn "Revit $($f.Directory.Name) manifest $($f.Name) does not point at an existing pyRevit 7 loader." }
    }
    foreach ($y in $machineYears) {
        if (-not ($userManifests | Where-Object { $_.Directory.Name -eq $y })) {
            Warn "Revit $y has a machine-wide pyRevit manifest but no per-user override: it will still load the old version. Run -Repoint."
        }
    }
    # Issue #258: one per-user pyRevit manifest per year, never with the machine-wide file name,
    # and with the machine-wide AddInId (another AddInId loads both pyRevit versions).
    foreach ($g in @($userManifests | Group-Object { $_.Directory.Name } | Where-Object { $_.Count -gt 1 })) {
        Warn "Revit $($g.Name) has $($g.Count) per-user pyRevit manifests ($(@($g.Group | ForEach-Object { $_.Name }) -join ', ')). Revit loads only one pyRevit, and which one is not fixed. Run -Repoint."
    }
    $sharedId = $false
    foreach ($mf in $machineFiles) {
        $y = $mf.Directory.Name
        $mid = Get-ManifestField $mf.FullName 'AddInId'
        foreach ($u in @($userManifests | Where-Object { $_.Directory.Name -eq $y })) {
            $uid = Get-ManifestField $u.FullName 'AddInId'
            if ($u.Name -ieq $mf.Name) {
                Warn "Revit $y : the per-user $($u.Name) has the same file name as the machine-wide manifest. Revit then reports it as duplicated, and Revit 2026.4 loaded no pyRevit. Run -Repoint."
            } elseif ($mid -and $uid -and $uid -ne $mid) {
                Warn "Revit $y : the per-user $($u.Name) has another AddInId than the machine-wide $($mf.Name), so Revit loads both pyRevit versions. Run -Repoint."
            } elseif ($mid -and $uid -eq $mid) { $sharedId = $true }
        }
    }
    if ($sharedId) {
        Say "IT installed a pyRevit for all users. At Revit start, a 'Duplicated AddInId' dialog for PyRevitLoader is expected: Revit refuses the second pyRevit. Close it. pyRevit > About must show 7.x."
    }

    if (Test-Path $Py7) {
        $agent = (Invoke-Cli $Py7 @('agent', 'status') | Out-String).Trim()
        $agent -split "`r?`n" | ForEach-Object { Say "agent: $_" }
        if ($agent -notmatch 'Agent host: enabled') { Warn 'Agent host is not enabled. Run -EnableAgent.' }
        $pol = Get-AgentPolicy
        if ($pol -eq 'ask' -or $pol -eq 'readonly') { Say "Agent policy: $pol" }
        else { Warn "Agent policy is '$pol'. Only 'ask' (Keep/Discard in Revit) or 'readonly' is safe. Run -EnableAgent to set 'ask'." }
        if ($agent -notmatch 'responding') {
            Say 'No Revit is connected yet. To finish: open Revit (restart it if it was already open), OPEN A MODEL (an Autodesk sample such as Snowdon Towers is fine), then run this script with -Verify again.'
        }
    }

    $claude = Find-ClaudeCli
    if ($claude) {
        if (Test-McpUsesPy7 $claude) { Say 'Claude Code MCP: pyrevit registered with the pyRevit 7 path.' }
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

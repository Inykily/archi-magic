<#
.SYNOPSIS
  Per-user auto-post state for the am-feedback skill.

.DESCRIPTION
  One small JSON file, %LOCALAPPDATA%\archi-magic\feedback-state.json:
    { "post_approvals": <int>, "auto_post": <bool> }
  The file is outside the plugin cache, so a plugin update keeps it.

  -Action Get         print the state. Changes nothing.
  -Action RecordPost  add 1 to post_approvals. Run it only after the user answers "Post".
                      auto_post becomes true when post_approvals is more than 10.
  -Action Off         set post_approvals to 0 and auto_post to false ("ask before posting").

  Every action prints one JSON line on stdout:
    {"post_approvals":N,"auto_post":true|false,"threshold":10,"path":"...","ok":true|false}
  ok is false when the file is unreadable. Then auto_post is false (ask mode), a WARN goes
  to stderr, and RecordPost does not overwrite the file. Run -Action Off to start again.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-feedback\scripts\feedback-state.ps1 -Action Get
#>
param(
    [ValidateSet('Get', 'RecordPost', 'Off')]
    [string]$Action = 'Get',
    [string]$StateFile = ''
)
$ErrorActionPreference = 'Stop'
$Threshold = 10

function Get-DefaultStatePath {
    $base = $env:LOCALAPPDATA
    if (-not $base -and $env:USERPROFILE) { $base = Join-Path $env:USERPROFILE 'AppData\Local' }
    if (-not $base) { return '' }
    return (Join-Path $base 'archi-magic\feedback-state.json')
}

function Write-Result([int]$Count, [bool]$Auto, [string]$Path, [bool]$Ok) {
    $o = New-Object PSObject -Property ([ordered]@{
        post_approvals = $Count; auto_post = $Auto; threshold = $Threshold; path = $Path; ok = $Ok
    })
    Write-Output (ConvertTo-Json -InputObject $o -Compress)
}

function Save-State([string]$Path, [int]$Count, [bool]$Auto) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $json = '{"post_approvals":' + $Count + ',"auto_post":' + $Auto.ToString().ToLowerInvariant() + '}'
    # UTF-8 without a byte-order mark: Windows PowerShell 5.1 Set-Content would add one.
    [IO.File]::WriteAllText($Path, $json, (New-Object Text.UTF8Encoding $false))
}

$path = $StateFile
if (-not $path) { $path = Get-DefaultStatePath }
if (-not $path) {
    [Console]::Error.WriteLine('WARN: no LOCALAPPDATA or USERPROFILE. Auto-post stays off.')
    Write-Result 0 $false '' $false
    exit 1
}

if ($Action -eq 'Off') {
    Save-State $path 0 $false
    Write-Result 0 $false $path $true
    exit 0
}

# Read the state. A missing file is a fresh start. An unreadable file means ask mode.
$count = 0
$ok = $true
if (Test-Path -LiteralPath $path) {
    try {
        $obj = [IO.File]::ReadAllText($path) | ConvertFrom-Json
        if ($null -eq $obj) { throw 'empty state file' }
        $n = $obj.post_approvals
        if ($null -eq $n -or -not ([string]$n -match '^\d{1,9}$')) { throw 'post_approvals is not a whole number' }
        $count = [int]$n
    } catch {
        $ok = $false
        [Console]::Error.WriteLine("WARN: cannot read the feedback state file ($($_.Exception.Message)). Auto-post stays off. Run -Action Off to start again.")
    }
}

if (-not $ok) {
    Write-Result 0 $false $path $false
    exit 0
}

if ($Action -eq 'RecordPost') {
    $count = $count + 1
    Save-State $path $count ($count -gt $Threshold)
}

# auto_post comes from the count, so a hand-edited "auto_post" cannot turn it on alone.
Write-Result $count ($count -gt $Threshold) $path $true
exit 0

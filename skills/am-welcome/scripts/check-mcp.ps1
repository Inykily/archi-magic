# check-mcp.ps1 - is the pyrevit MCP server registered with Claude Code? Read-only.
# Windows PowerShell 5.1. ASCII only.
# Finds the Claude Code CLI the same way as am-pyrevit7-setup\scripts\pyrevit7-setup.ps1
# (Find-ClaudeCli; keep the two copies in step). The Claude desktop app's own exe
# (AnthropicClaude\claude.exe) is NOT the CLI and is never used.
# Output: one line "registered", "not-registered" or "no-cli".
# Exit codes: 0 registered, 3 not registered, 4 Claude Code CLI not found.

$ErrorActionPreference = 'Continue'

function Find-ClaudeCli {
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

$claude = Find-ClaudeCli
if (-not $claude) { Write-Output 'no-cli'; exit 4 }
$out = (& $claude mcp get pyrevit 2>&1 | Out-String)
if ($LASTEXITCODE -eq 0 -and $out -match 'pyrevit') { Write-Output 'registered'; exit 0 }
Write-Output 'not-registered'
exit 3

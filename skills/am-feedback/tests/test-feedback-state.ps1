<#
.SYNOPSIS
  Tests for skills/am-feedback/scripts/feedback-state.ps1 (the auto-post counter).
  Hermetic: a temp state file. No network, no GitHub.

  powershell -NoProfile -ExecutionPolicy Bypass -File skills\am-feedback\tests\test-feedback-state.ps1
  Exit 0 = all cases pass.
#>
$ErrorActionPreference = 'Stop'
$Script = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\feedback-state.ps1')).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ("am-feedback-state-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$script:Fail = 0; $script:Asserts = 0

function Invoke-State([string]$state, [string]$action) {
    # Run it the way the skill does: a separate Windows PowerShell process.
    $ErrorActionPreference = 'Continue'
    $err = Join-Path $Root 'stderr.txt'
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Action $action -StateFile $state 2>$err | Out-String
    $code = $LASTEXITCODE
    $errText = ''
    if (Test-Path -LiteralPath $err) { $errText = [IO.File]::ReadAllText($err) }
    $j = $null
    try { $j = $out.Trim() | ConvertFrom-Json } catch { }
    return @{ Code = $code; Out = $out.Trim(); Err = $errText; J = $j }
}
function Assert-True([string]$name, [bool]$ok, [string]$detail) {
    $script:Asserts++
    if ($ok) { Write-Host "PASS $name" } else { $script:Fail++; Write-Host "FAIL $name : $detail" }
}
function Write-Raw([string]$name, [string]$text) {
    $p = Join-Path $Root $name
    [IO.File]::WriteAllText($p, $text, (New-Object Text.UTF8Encoding $false))
    return $p
}

try {
    New-Item -ItemType Directory -Force $Root | Out-Null

    # 1. No file: count 0, ask mode, and Get does not create the file.
    $s = Join-Path $Root 'fresh.json'
    $r = Invoke-State $s 'Get'
    Assert-True 'fresh: exit 0, count 0, ask mode' ($r.Code -eq 0 -and $r.J.post_approvals -eq 0 -and $r.J.auto_post -eq $false -and $r.J.ok -eq $true) $r.Out
    Assert-True 'fresh: Get writes nothing' (-not (Test-Path -LiteralPath $s)) 'file created'

    # 2. First RecordPost creates the file with count 1, BOM-free JSON.
    $r = Invoke-State $s 'RecordPost'
    Assert-True 'first post: count 1, ask mode' ($r.J.post_approvals -eq 1 -and $r.J.auto_post -eq $false) $r.Out
    $bytes = [IO.File]::ReadAllBytes($s)
    Assert-True 'first post: no byte-order mark' ($bytes[0] -ne 0xEF) "first byte $($bytes[0])"
    Assert-True 'first post: file content' ([IO.File]::ReadAllText($s) -eq '{"post_approvals":1,"auto_post":false}') ([IO.File]::ReadAllText($s))

    # 3. Boundary: 9 -> 10 stays in ask mode.
    $s = Write-Raw 'nine.json' '{"post_approvals":9,"auto_post":false}'
    $r = Invoke-State $s 'RecordPost'
    Assert-True '9 -> 10: still ask mode' ($r.J.post_approvals -eq 10 -and $r.J.auto_post -eq $false) $r.Out
    Write-Host "  shown: $($r.Out)"

    # 4. 10 -> 11 turns auto mode on, and it stays on.
    $r = Invoke-State $s 'RecordPost'
    Assert-True '10 -> 11: auto mode on' ($r.J.post_approvals -eq 11 -and $r.J.auto_post -eq $true) $r.Out
    Write-Host "  shown: $($r.Out)"
    Assert-True '10 -> 11: file says auto' ([IO.File]::ReadAllText($s) -eq '{"post_approvals":11,"auto_post":true}') ([IO.File]::ReadAllText($s))
    $r = Invoke-State $s 'Get'
    Assert-True 'after 11: Get says auto, count unchanged' ($r.J.post_approvals -eq 11 -and $r.J.auto_post -eq $true) $r.Out
    Write-Host "  shown: $($r.Out)"

    # 5. Off resets to 0 and ask mode.
    $r = Invoke-State $s 'Off'
    Assert-True 'off: count 0, ask mode' ($r.Code -eq 0 -and $r.J.post_approvals -eq 0 -and $r.J.auto_post -eq $false) $r.Out
    Assert-True 'off: file reset' ([IO.File]::ReadAllText($s) -eq '{"post_approvals":0,"auto_post":false}') ([IO.File]::ReadAllText($s))

    # 6. A hand-edited auto_post without the count does not turn auto mode on.
    $s = Write-Raw 'forged.json' '{"post_approvals":2,"auto_post":true}'
    $r = Invoke-State $s 'Get'
    Assert-True 'forged auto flag: ask mode' ($r.J.auto_post -eq $false) $r.Out

    # 7. A corrupt file: ask mode, WARN on stderr, file kept as it was.
    $s = Write-Raw 'corrupt.json' '{"post_approvals": oops'
    $r = Invoke-State $s 'RecordPost'
    Assert-True 'corrupt: ask mode, ok false' ($r.Code -eq 0 -and $r.J.auto_post -eq $false -and $r.J.ok -eq $false) $r.Out
    Assert-True 'corrupt: WARN on stderr' ($r.Err -match 'WARN') $r.Err
    Assert-True 'corrupt: file not overwritten' ([IO.File]::ReadAllText($s) -eq '{"post_approvals": oops') ([IO.File]::ReadAllText($s))

    # 8. A count that is not a whole number is corrupt too.
    $s = Write-Raw 'text.json' '{"post_approvals":"many","auto_post":true}'
    $r = Invoke-State $s 'Get'
    Assert-True 'non-number count: ask mode, ok false' ($r.J.auto_post -eq $false -and $r.J.ok -eq $false) $r.Out
}
finally {
    Remove-Item -Recurse -Force -LiteralPath $Root -ErrorAction SilentlyContinue
}

Write-Host "$($script:Asserts) assertions, $($script:Fail) failed"
if ($script:Asserts -eq 0) { Write-Host 'FAIL: no assertions ran'; exit 1 }
if ($script:Fail -gt 0) { exit 1 }
exit 0

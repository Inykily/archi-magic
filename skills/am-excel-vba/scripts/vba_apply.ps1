<#
.SYNOPSIS
  Apply a reviewed am-excel-vba plan to a NEW COPY of a macro workbook.

.DESCRIPTION
  -CheckTrust only reads the "Trust access to the VBA project object model"
  setting (registry value AccessVBOM) and reports it. It never changes it.

  With -Plan and -Output the script:
    1. reads the plan file that vba_project.py plan wrote;
    2. stops if the output exists, is the source, or has another extension;
    3. stops if the source changed after the preview (SHA-256);
    4. stops if trust access is not on (it does not change the setting);
    5. copies the source to the output;
    6. opens the copy in a new, hidden Excel with macros disabled;
    7. checks every anchor line and the line counts, then edits the code;
    8. saves the copy, closes it and quits only the Excel it started.
  The source workbook is never opened and never written.
  It does not compile the project (the compile result shows only as a dialog).
  On a failure it closes the copy without saving and deletes the copy it made.

  Exit codes: 0 saved (or trust on), 2 input error, 3 trust access off,
  4 project locked, 5 the copy does not match the plan, 6 Excel error.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File vba_apply.ps1 -CheckTrust
  powershell -NoProfile -ExecutionPolicy Bypass -File vba_apply.ps1 -Plan plan.json -Output "C:\work\Book (fixed).xlsm"
#>
param(
    [string]$Plan,
    [string]$Output,
    [switch]$CheckTrust
)
$ErrorActionPreference = 'Stop'

function Write-Result($status, $message, $code, $extra) {
    $o = [ordered]@{ status = $status; message = $message }
    if ($extra) { foreach ($k in $extra.Keys) { $o[$k] = $extra[$k] } }
    $o | ConvertTo-Json -Depth 5
    exit $code
}

function Get-TrustAccess {
    # Returns @{ on = bool; source = text }. Policy keys win over the user setting.
    $roots = @(
        @{ path = 'HKCU:\Software\Policies\Microsoft\Office'; policy = $true },
        @{ path = 'HKLM:\Software\Policies\Microsoft\Office'; policy = $true },
        @{ path = 'HKCU:\Software\Microsoft\Office'; policy = $false }
    )
    foreach ($r in $roots) {
        if (-not (Test-Path -LiteralPath $r.path)) { continue }
        $versions = @(Get-ChildItem -LiteralPath $r.path -ErrorAction SilentlyContinue |
            Where-Object { $_.PSChildName -match '^\d+\.\d+$' } | Sort-Object { [double]$_.PSChildName } -Descending)
        foreach ($v in $versions) {
            $key = Join-Path $v.PSPath 'Excel\Security'
            if (-not (Test-Path -LiteralPath $key)) { continue }
            $item = Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
            if ($null -eq $item -or $null -eq $item.PSObject.Properties['AccessVBOM']) { continue }
            $kind = 'user setting'
            if ($r.policy) { $kind = 'policy set by IT' }
            return @{ on = ([int]$item.AccessVBOM -eq 1); source = ($kind + ', Office ' + $v.PSChildName); value = [int]$item.AccessVBOM }
        }
    }
    return @{ on = $false; source = 'not set'; value = $null }
}

$trustSteps = 'In Excel: File > Options > Trust Center > Trust Center Settings > Macro Settings. ' +
    'Tick "Trust access to the VBA project object model". Click OK in Trust Center, then OK in Excel Options. Close Excel.'

if ($CheckTrust) {
    $t = Get-TrustAccess
    if ($t.on) { Write-Result 'trust_on' 'Trust access to the VBA project is on.' 0 @{ source = $t.source } }
    Write-Result 'trust_off' ('Trust access to the VBA project is off. ' + $trustSteps) 3 @{ source = $t.source; value = $t.value }
}

if (-not $Plan -or -not $Output) { Write-Result 'input_error' 'Give -Plan and -Output, or -CheckTrust.' 2 $null }
if (-not (Test-Path -LiteralPath $Plan -PathType Leaf)) { Write-Result 'input_error' 'The plan file does not exist.' 2 $null }
try {
    $planObj = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $Plan).ProviderPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
} catch { Write-Result 'input_error' 'The plan file is not valid JSON.' 2 $null }
if ($planObj.format -ne 'am-excel-vba-plan/1') { Write-Result 'input_error' 'The file is not an am-excel-vba plan.' 2 $null }

$source = [string]$planObj.source
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { Write-Result 'input_error' 'The source workbook in the plan does not exist.' 2 $null }
$sourceFull = (Resolve-Path -LiteralPath $source).ProviderPath
$outFull = [IO.Path]::GetFullPath($Output)
if ([string]::Equals($sourceFull, $outFull, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Result 'input_error' 'The output is the source workbook. Give a new file name.' 2 $null
}
if (Test-Path -LiteralPath $outFull) { Write-Result 'input_error' 'The output file already exists. Give a new file name.' 2 $null }
if ([IO.Path]::GetExtension($outFull) -ne [IO.Path]::GetExtension($sourceFull)) {
    Write-Result 'input_error' 'The output must have the same extension as the source.' 2 $null
}
$outDir = Split-Path -Parent $outFull
if (-not (Test-Path -LiteralPath $outDir -PathType Container)) { Write-Result 'input_error' 'The output folder does not exist.' 2 $null }
$hash = (Get-FileHash -LiteralPath $sourceFull -Algorithm SHA256).Hash.ToLowerInvariant()
if ($hash -ne ([string]$planObj.source_sha256).ToLowerInvariant()) {
    Write-Result 'input_error' 'The source workbook changed after the preview. Make a new plan.' 2 $null
}
$steps = @($planObj.steps)
if ($steps.Count -eq 0) { Write-Result 'input_error' 'The plan has no steps.' 2 $null }

$trust = Get-TrustAccess
if (-not $trust.on) {
    Write-Result 'trust_off' ('Trust access to the VBA project is off. No file was written. ' + $trustSteps) 3 @{ source = $trust.source }
}

Copy-Item -LiteralPath $sourceFull -Destination $outFull
$excel = $null; $wb = $null; $saved = $false
$status = 'excel_error'; $message = ''; $code = 6
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3   # msoAutomationSecurityForceDisable: no macro runs
    $wb = $excel.Workbooks.Open($outFull, 0, $false)
    $project = $null
    try { $project = $wb.VBProject } catch { $project = $null }
    if ($null -eq $project) {
        $status = 'trust_off'; $code = 3
        throw ('Excel returned no VBA project, so trust access is off for this Excel. ' + $trustSteps)
    }
    if ($project.Protection -eq 1) {
        $status = 'locked'; $code = 4
        throw 'The VBA project is locked with a password. Ask the user to unlock it in Excel first.'
    }
    # Check every anchor and line count on the unchanged copy before the first edit.
    $modules = @{}
    foreach ($step in $steps) {
        $name = [string]$step.module
        if (-not $modules.ContainsKey($name)) {
            $comp = $null
            try { $comp = $project.VBComponents.Item($name) } catch { $comp = $null }
            if ($null -eq $comp) { $status = 'mismatch'; $code = 5; throw "Module $name is not in the copy." }
            $cm = $comp.CodeModule
            $expectedCount = [int]$planObj.modules.$name.code_lines
            if ($cm.CountOfLines -ne $expectedCount) {
                $status = 'mismatch'; $code = 5
                throw "Module $name has $($cm.CountOfLines) lines in Excel and $expectedCount in the plan."
            }
            $modules[$name] = $cm
        }
        $actual = [string]$modules[$name].Lines([int]$step.line, 1)
        if ($actual.TrimEnd() -cne ([string]$step.anchor_text).TrimEnd()) {
            $status = 'mismatch'; $code = 5
            throw "Line $($step.line) of $name is not the planned line."
        }
    }
    # Steps come in descending line order for each module, so earlier line numbers stay valid.
    foreach ($step in $steps) {
        $cm = $modules[[string]$step.module]
        $line = [int]$step.line
        $text = (@($step.insert) | ForEach-Object { [string]$_ }) -join "`r`n"
        switch ([string]$step.action) {
            'insert_before' { $cm.InsertLines($line, $text) }
            'insert_after'  { $cm.InsertLines($line + 1, $text) }
            'replace'       { $cm.DeleteLines($line, 1); if (@($step.insert).Count -gt 0) { $cm.InsertLines($line, $text) } }
            'delete'        { $cm.DeleteLines($line, 1) }
            default         { $status = 'input_error'; $code = 2; throw "Unknown action $($step.action)." }
        }
    }
    $wb.Save()
    $saved = $true
    $status = 'saved'; $code = 0
    $message = 'The copy is saved. Run vba_project.py verify on it. Then compile it in Excel (Debug > Compile VBAProject).'
} catch {
    if (-not $message) { $message = $_.Exception.Message }
} finally {
    if ($null -ne $wb) { try { $wb.Close($false) } catch { } }
    if ($null -ne $excel) {
        try { $excel.Quit() } catch { }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
    if (-not $saved -and (Test-Path -LiteralPath $outFull)) {
        try { Remove-Item -LiteralPath $outFull -Force } catch { }
    }
}
if ($saved) { Write-Result $status $message $code @{ output = $outFull; steps = $steps.Count } }
Write-Result $status ($message + ' No file was kept.') $code $null

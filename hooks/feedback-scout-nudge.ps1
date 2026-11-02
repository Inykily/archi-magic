<#
.SYNOPSIS
  archi-magic hook: about every 2 hours, ask the agent to run the feedback scout.

.DESCRIPTION
  Runs on SessionStart and on UserPromptSubmit. It reads one small state file,
  %LOCALAPPDATA%\archi-magic\feedback-scout.json, with the time of the last
  nudge. When the interval has passed, it writes the new time and prints one
  JSON object:
    - systemMessage: a short line for the user.
    - additionalContext: tells the agent to dispatch the read-only agent
      archi-magic:am-feedback-scout in the background right away, without
      asking first, with since = the previous nudge time. The scout only drafts; posting stays
      with the am-feedback skill after the user says "Post".

  The first run only writes the start time and prints nothing, so a new
  install does not nudge at once. Inside the interval it prints nothing.

  Interval: 120 minutes. Set ARCHI_MAGIC_SCOUT_INTERVAL_MIN to change it;
  0 turns the scout nudge off. Opt out of all feedback nudges with
  ARCHI_MAGIC_NO_FEEDBACK_NUDGE=1.

  Speed: one small file read and write, no transcript read, no network.
  Never blocks a session: always exit 0. Every failure goes to the shared
  archi-magic log.

  Test parameters: -HookInputJson (the hook input JSON), -StateFile,
  -NowUtc (ISO 8601).
#>
param(
    [string]$HookInputJson = '',
    [string]$StateFile = '',
    [string]$NowUtc = ''
)
$ErrorActionPreference = 'Stop'

function Write-Log([string]$Level, [string]$Message, [hashtable]$Data) {
    try {
        . (Join-Path $PSScriptRoot '..\scripts\lib\am-log.ps1')
        # Write-AmLog warns on a log failure; keep stdout clean for the hook JSON.
        Write-AmLog -Skill 'hooks' -Step 'feedback-scout-nudge' -Level $Level -Message $Message -Data $Data 3>$null
    } catch { }
}

function Save-State([string]$Path, [datetime]$When) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $obj = New-Object PSObject -Property ([ordered]@{ last_nudge = $When.ToString('o') })
    [IO.File]::WriteAllText($Path, ($obj | ConvertTo-Json -Compress))
}

try {
    if ($env:ARCHI_MAGIC_NO_FEEDBACK_NUDGE -eq '1') { exit 0 }

    $interval = 120
    if ($env:ARCHI_MAGIC_SCOUT_INTERVAL_MIN) {
        $parsed = 0
        if ([int]::TryParse($env:ARCHI_MAGIC_SCOUT_INTERVAL_MIN, [ref]$parsed)) { $interval = $parsed }
        else { Write-Log 'warn' 'ARCHI_MAGIC_SCOUT_INTERVAL_MIN is not a number; using 120' $null }
    }
    if ($interval -le 0) { exit 0 }

    $hookEvent = 'UserPromptSubmit'
    if ($HookInputJson) {
        try {
            $hookInput = $HookInputJson | ConvertFrom-Json
            if ($hookInput.hook_event_name) { $hookEvent = [string]$hookInput.hook_event_name }
        } catch { }
    }
    if ($hookEvent -ne 'SessionStart' -and $hookEvent -ne 'UserPromptSubmit') { exit 0 }

    $now = (Get-Date).ToUniversalTime()
    if ($NowUtc) { $now = ([datetime]::Parse($NowUtc, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AdjustToUniversal)) }

    if (-not $StateFile) {
        $base = $env:LOCALAPPDATA
        if (-not $base) { $base = Join-Path $env:USERPROFILE 'AppData\Local' }
        if (-not $base) { exit 0 }
        $StateFile = Join-Path $base 'archi-magic\feedback-scout.json'
    }

    $last = $null
    if (Test-Path -LiteralPath $StateFile) {
        try {
            $state = [IO.File]::ReadAllText($StateFile) | ConvertFrom-Json
            $last = [datetime]::Parse([string]$state.last_nudge, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AdjustToUniversal)
        } catch {
            Write-Log 'warn' 'Scout state unreadable; starting a new interval' $null
            $last = $null
        }
    }

    # First run, or an unreadable state file: start the clock, nudge later.
    if ($null -eq $last) {
        Save-State $StateFile $now
        exit 0
    }
    if (($now - $last).TotalMinutes -lt $interval) { exit 0 }

    Save-State $StateFile $now
    $since = $last.ToString('o')
    $user = "archi-magic: $interval minutes since the last feedback scout. " +
            'A read-only scout now runs in the background over recent archi-magic sessions. You will see what is worth reporting when it is done. Nothing is posted without your "Post".'
    $ctx = "archi-magic feedback scout is due (interval $interval minutes; previous nudge $since UTC). " +
           "Dispatch the agent archi-magic:am-feedback-scout in the background now, with the input since=$since. " +
           'Do not wait for a pause and do not ask the user first: the scout is read-only and runs in parallel with the current work. ' +
           'When it returns, show the user its themes as a short list and offer to post them, ' +
           'but do not interrupt a model change, a dry run or a Keep/Discard prompt to do so. ' +
           'Post nothing yourself: if the user wants to post, use the am-feedback skill, which posts only after the user says "Post".'
    $out = [ordered]@{
        systemMessage      = $user
        hookSpecificOutput = [ordered]@{ hookEventName = $hookEvent; additionalContext = $ctx }
    }
    [Console]::Out.Write((New-Object PSObject -Property $out | ConvertTo-Json -Compress -Depth 3))
    Write-Log 'info' 'Feedback scout nudge shown' @{ event = $hookEvent; interval = $interval }
} catch {
    Write-Log 'error' ('Feedback scout nudge failed: ' + $_.Exception.Message) $null
}
exit 0

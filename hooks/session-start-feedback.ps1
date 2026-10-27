<#
.SYNOPSIS
  archi-magic SessionStart hook: show a saved session-end feedback note, once.

.DESCRIPTION
  The SessionEnd hook (hooks/session-end-feedback.ps1) saves one small JSON
  note to %LOCALAPPDATA%\archi-magic\session-feedback.json when a session ends
  with trouble (Revit connection errors, failed tool calls, the user saying
  something is broken). This hook reads that note at the next session start
  and shows it once, then deletes it.

  Why a second hook: Claude Code discards a SessionEnd hook's JSON output
  (systemMessage included), so the SessionEnd hook cannot tell the user
  anything itself. A SessionStart hook can: its systemMessage is shown to the
  user, and its additionalContext reaches the agent, which is alive again and
  can file the issue if the user says yes.

  Output: nothing when there is no note. With a note, one JSON object:
  systemMessage (shown to the user: what went wrong, the offer to file it)
  and additionalContext (for the agent: the signals, the suggested title and
  body draft, the rule to file only if the user says yes).

  Never blocks a session: always exit 0. Every failure goes to the shared
  archi-magic log. Opt out: set ARCHI_MAGIC_NO_FEEDBACK_NUDGE=1 (a saved
  note is deleted).

  Test parameters: -FeedbackFile.
#>
param(
    [string]$FeedbackFile = ''
)
$ErrorActionPreference = 'Stop'

function Write-Log([string]$Level, [string]$Message, [hashtable]$Data) {
    try {
        . (Join-Path $PSScriptRoot '..\scripts\lib\am-log.ps1')
        # Write-AmLog warns on a log failure; keep stdout clean for the hook JSON.
        Write-AmLog -Skill 'hooks' -Step 'session-start-feedback' -Level $Level -Message $Message -Data $Data 3>$null
    } catch { }
}

try {
    if (-not $FeedbackFile) {
        $base = $env:LOCALAPPDATA
        if (-not $base) { $base = Join-Path $env:USERPROFILE 'AppData\Local' }
        if (-not $base) { exit 0 }
        $FeedbackFile = Join-Path $base 'archi-magic\session-feedback.json'
    }
    if (-not (Test-Path -LiteralPath $FeedbackFile)) { exit 0 }
    if ($env:ARCHI_MAGIC_NO_FEEDBACK_NUDGE -eq '1') {
        try { Remove-Item -Force -LiteralPath $FeedbackFile } catch { }
        exit 0
    }

    $note = $null
    try { $note = [IO.File]::ReadAllText($FeedbackFile) | ConvertFrom-Json } catch { }
    # Consume once: delete even when the note is unreadable, so a bad file
    # cannot nag at every session start.
    try { Remove-Item -Force -LiteralPath $FeedbackFile } catch { Write-Log 'warn' 'Feedback note not deleted' $null }
    if ($null -eq $note -or -not $note.title) {
        Write-Log 'warn' 'Feedback note unreadable; deleted' $null
        exit 0
    }

    $signals = ''
    if ($note.signals) { $signals = (@($note.signals) -join ', ') }
    $user = "Last session hit a problem: $($note.title). " +
            'Want to file it as a GitHub issue on archi-magic? ' +
            "Suggested title: $($note.title). Say yes and I will draft it with you."
    $ctx = "A previous archi-magic session ended with trouble. Signals: $signals. " +
           "Suggested issue title: $($note.title). " +
           "Suggested body draft: $($note.body) " +
           "Session ended (UTC): $($note.ended_at). Transcript: $($note.transcript) " +
           'Offer once: ask the user if they want to file it as a GitHub issue on zsenarchitect/archi-magic. ' +
           'File it only if the user says yes. Route: gh issue create --repo zsenarchitect/archi-magic --title "<title>" --body "<body>". ' +
           'Never file it without the user saying yes. If the user says no, drop it.'
    $out = [ordered]@{
        systemMessage      = $user
        hookSpecificOutput = [ordered]@{ hookEventName = 'SessionStart'; additionalContext = $ctx }
    }
    [Console]::Out.Write((New-Object PSObject -Property $out | ConvertTo-Json -Compress -Depth 3))
    Write-Log 'info' 'Feedback note shown' @{ signals = $signals }
} catch {
    Write-Log 'error' ('Feedback note not shown: ' + $_.Exception.Message) $null
}
exit 0

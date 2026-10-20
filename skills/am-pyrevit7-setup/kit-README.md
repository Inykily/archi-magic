# pyRevit 7 + Agent Runtime kit (no admin rights)

This kit sets three things up for the current Windows user:
1. **pyRevit 7**, installed per-user. No admin rights needed.
2. **Revit 2024–2026 repointed** to pyRevit 7. This works even when IT installed an older pyRevit (6.x) machine-wide.
3. **The pyRevit Agent Runtime connected to Claude Code**, so Claude can read and edit your open Revit model.

## Option A: double-click (about 2 minutes)

1. Save your work and **close Revit**.
2. Double-click **`Setup-pyRevit7.cmd`**. Wait for `Done. No problems found.`, then press a key.
3. Open Revit and **open a model**. The connection check needs one. Any Autodesk sample model is fine, for example *Snowdon Towers Sample Architectural* from the Home screen.
4. Check pyRevit → About. It should say **7.0**. A duplicate add-in warning at startup is expected and harmless.
5. Double-click `Setup-pyRevit7.cmd` again. This time the Verify section shows `Revit 20xx ... responding`.
6. Restart the Claude desktop app. In a **new** Code session, ask Claude: *"use the pyrevit tools to get the context of my open Revit model"*.

## Option B: let Claude Code do it

With the archi-magic plugin installed, ask Claude Code to "set up pyRevit 7". The `am-pyrevit7-setup` skill runs the same script and walks you through the Revit check.

## Good to know

- **Re-run the kit after any pyRevit update.** The pyRevit installer and `pyrevit attach` remove the per-user fix, so Revit can fall back to 6.x. Re-running is safe; `Setup-pyRevit7.cmd -Repoint -Verify` only repoints and checks.
- **Approvals:** every model change Claude makes asks for your approval inside Revit. **Keep** commits it as one undo step. **Discard** rolls it back.
- **Data:** anything Claude reads from the model is sent to the AI provider. Only use this on projects where that's allowed. Run records are stored under `%APPDATA%\pyRevit\agent` for 14 days.
- **Undo:** delete `%APPDATA%\Autodesk\Revit\Addins\<year>\pyRevit.addin`. Then run `"%APPDATA%\pyRevit-Master\bin\pyrevit.exe" mcp uninstall claude` and `... configs agent disable`.
- **Logs and backups:** each run writes a log and backs up any manifest it replaces under `%TEMP%\pyrevit7-setup\<timestamp>\`.
- **Clean long-term fix (IT, needs admin):** uninstall the machine-wide pyRevit 6.x, or delete `C:\ProgramData\Autodesk\Revit\Addins\<year>\pyRevit.addin`. The per-user setup keeps working after that.

## Script switches

`pyrevit7-setup.ps1 [-Install] [-Repoint] [-EnableAgent] [-Verify] [-Force] [-Policy ask|readonly]`. With no switch, it runs all four steps. `-Force` reinstalls even when 7.x is present.

`-EnableAgent` sets the agent policy to `ask`, so every model change needs Keep/Discard in Revit. Use `-Policy readonly` to block all model changes. The script never sets `auto` (changes without approval). `-Verify` reports a problem when the policy is not `ask` or `readonly`.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | Unexpected error. Read the log that the script names. |
| 2 | Close Revit first |
| 3 | Install failed |
| 4 | Repoint failed |
| 5 | Agent setup incomplete |
| 6 | Verify found problems |

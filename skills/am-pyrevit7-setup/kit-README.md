# pyRevit 7 + Agent Runtime kit (no admin rights)

This kit sets three things up for the current Windows user:
1. **pyRevit 7**, installed per-user. No admin rights needed.
2. **Revit 2024–2026 repointed** to pyRevit 7. This works even when IT installed an older pyRevit (6.x) machine-wide.
3. **The pyRevit Agent Runtime connected to Claude Code**, so Claude can read and edit your open Revit model.

## Read this first: your data

Read this before you start the setup.

- Claude sends what it reads from the model to the AI provider. This includes element data, parameter values, pictures of views (`capture_view` takes them), and project and file names.
- pyRevit keeps a plain-text record of each run in `%APPDATA%\pyRevit\agent` for up to 14 days. This folder is in your Roaming profile, so it can copy to your office servers.
- Claude keeps the chat records in `%USERPROFILE%\.claude\projects`.
- If you are not sure the project allows AI tools, ask your BIM manager first.

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
- **Data:** see "Read this first: your data" above.
- **Undo:** delete `%APPDATA%\Autodesk\Revit\Addins\<year>\pyRevit.addin`. Then run `"%APPDATA%\pyRevit-Master\bin\pyrevit.exe" mcp uninstall claude` and `... configs agent disable`.
- **Installer check:** the script downloads the latest pyRevit release from GitHub. It runs the installer only when the file matches the SHA256 checksum from GitHub and the signature is valid and comes from the known pyRevit signer (Jean-Marc Couffin, through Microsoft ID Verified signing). If one check fails, the script stops with exit code 3 and does not run the installer.
- **Logs and backups:** each run writes a log and backs up any manifest it replaces under `%TEMP%\pyrevit7-setup\<timestamp>\`.
- **Clean long-term fix (IT, needs admin):** uninstall the machine-wide pyRevit 6.x, or delete `C:\ProgramData\Autodesk\Revit\Addins\<year>\pyRevit.addin`. The per-user setup keeps working after that.

## Script switches

`pyrevit7-setup.ps1 [-Install] [-Repoint] [-EnableAgent] [-Verify] [-Force] [-Policy ask|readonly]`. With no switch, it runs all four steps. `-Force` reinstalls even when 7.x is present.

`-EnableAgent` sets the agent policy to `ask`, so every model change needs Keep/Discard in Revit. Use `-Policy readonly` to block all model changes. A re-run keeps an existing `readonly` policy unless you pass `-Policy`. The script never sets `auto` (changes without approval). `-Verify` reports a problem when the policy is not `ask` or `readonly`.

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

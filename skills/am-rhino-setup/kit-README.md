# Rhino MCP kit for Claude Code (no admin rights)

This kit sets up three things for the current Windows user:
1. **McNeel's Rhino MCP plugin** (`Rhino-MCP-Platform`), installed per-user with Yak, Rhino's package manager. No admin rights needed.
2. **The `rhino` MCP server in Claude Code.** It points at McNeel's router, `%APPDATA%\McNeel\Rhinoceros\ai\bin\rhino-mcp-router.exe`. The router talks to Rhino over stdio (standard input and output).
3. **Ask rules.** Claude Code must ask you before every `run_python`, `run_csharp` and `run_command` call in Rhino.

Source: https://github.com/mcneel/RhinoAI (MIT). Docs: https://mcneel.github.io/RhinoAI/docs/

## Option A: let Claude Code do it

With the archi-magic plugin installed, ask Claude Code to "set up Rhino". The `am-rhino-setup` skill runs the script and walks you through the Rhino check.

## Option B: run the script yourself

1. Run `powershell -NoProfile -ExecutionPolicy Bypass -File rhino-setup.ps1`. Wait for `Done. No problems found.`
2. Open Rhino 8 (restart it if it was open). Type `SetDotNetRuntime`. It must say **NETCore**.
3. Restart the Claude desktop app. In a **new** Code session, ask: *"use the rhino tools to list the objects in my open Rhino document"*.

If Yak cannot install the plugin, install it in Rhino: type `PackageManager`, search for **Rhino-MCP-Platform**, click Install, and restart Rhino. Then run the script with `-Connect -Verify`.

## Good to know

- **Approvals:** Rhino has no Keep/Discard step. Claude Code asks before it runs code or commands in Rhino. Read each request. Use Undo in Rhino to reverse a change. Save your file first.
- **Not covered by the ask rules:** tools such as `open_doc`, `save_doc`, `close_doc`, `set_layer_material` and the Grasshopper tools also change files or the model. They follow your normal permission mode (in auto mode, the classifier decides, not you).
- **Data:** anything Claude reads from the model, and every viewport image, goes to the AI provider. Use it only on projects where that is allowed.
- **Several Rhino windows:** Claude can edit a different document than the one you look at. Keep one Rhino open. If no Rhino is open, a tool call can start one.
- **Rhino 9 WIP/BETA:** run with `-RhinoVersion 9`. This adds `--default-version 9` to the router command.
- **Logs and backups:** each run writes a log under `%TEMP%\rhino-setup\<timestamp>\`. Before it changes `settings.json`, the script writes a backup next to it: `settings.json.am-rhino-backup-<timestamp>`.
- **Undo:** run `claude mcp remove rhino -s user`. Remove the three `mcp__rhino__*` lines from `permissions.ask` in `%USERPROFILE%\.claude\settings.json`. Run `"C:\Program Files\Rhino 8\System\Yak.exe" uninstall Rhino-MCP-Platform`.

## Script switches

`rhino-setup.ps1 [-Install] [-Connect] [-AskRules] [-Verify] [-Force] [-RhinoVersion 8|9] [-SettingsPath <file>]`. With no switch, it runs Install, Connect (which includes AskRules) and Verify. `-Force` runs `yak install` again. `-SettingsPath` changes the settings file (default `%USERPROFILE%\.claude\settings.json`).

Exit codes:

| Code | Meaning |
|---|---|
| 0 | OK |
| 2 | Rhino 8 (or the selected version) is not installed |
| 3 | Plugin install failed |
| 4 | MCP registration incomplete |
| 5 | settings.json not changed (invalid JSON or unexpected shape) |
| 6 | Verify found problems |

---
name: am-pyrevit7-setup
description: Install pyRevit 7 per-user on Windows WITHOUT admin rights, repoint Revit 2024-2026 to it (overriding an admin-owned machine-wide pyRevit 6.x), enable the pyRevit Agent Runtime, and register its MCP server with Claude Code so Claude can read and edit the open Revit model. Also the fix when Revit still loads pyRevit 6.x after installing 7, or after any pyRevit update or `pyrevit attach` broke it. Triggers on "install pyrevit 7", "update pyrevit", "pyrevit still shows 6.4", "connect claude to revit", "pyrevit agent runtime", "pyrevit mcp", "revit agent setup".
---

# am-pyrevit7-setup

Sets up pyRevit 7 and the pyRevit Agent Runtime (https://docs.pyrevitlabs.io/agent-runtime/) for the current Windows user. All the work is done by the tested script `scripts/pyrevit7-setup.ps1` in this skill's directory. **Run it, don't reimplement it.** Background and the exit-code table are in `kit-README.md`.

## Rules

- The user has **no admin rights**. Never try elevation, UAC or `-Verb RunAs`, and never uninstall the machine-wide pyRevit.
- **Never kill Revit.** If the script exits with code 2, ask the user to save and close Revit, then wait.
- Don't run the pyRevit installer with `/LOG` (it crashes intermittently), and don't run `pyrevit attach` yourself (on machines with an admin-installed pyRevit it deletes per-user manifests and then fails).
- Show the script's output, and explain every WARNING and every non-zero exit code.

## Steps

0. **Warn about data first, before any setup step.** Tell the user this in plain words:
   - Claude sends what it reads from the model to the AI provider. This includes element data, parameter values, pictures of views (`capture_view` takes them), and project and file names.
   - pyRevit keeps a plain-text record of each run in `%APPDATA%\pyRevit\agent` for up to 14 days. This folder is in your Roaming profile, so it can copy to your office servers.
   - Claude keeps the chat records in `%USERPROFILE%\.claude\projects`.
   - If you are not sure the project allows AI tools, ask your BIM manager first.

   Then use AskUserQuestion: "Do you want to continue with the setup?" Give two options: "Continue with setup" and "Stop, I will ask my BIM manager first". Do not mark an option as recommended; this is the user's decision. Run nothing until the user picks "Continue with setup". If the user picks "Stop", end the skill.
1. Run everything (install, repoint, enable agent, verify). It takes about 2 minutes:
   `powershell -NoProfile -ExecutionPolicy Bypass -File "<this skill dir>\scripts\pyrevit7-setup.ps1"`
   - For a quick re-fix after a pyRevit update, use `-Repoint -Verify` instead.
2. When it prints `Done`, ask the user to open Revit and **open a model**. The connection check can't finish from the Home screen. An Autodesk sample such as *Snowdon Towers Sample Architectural* is fine. If Revit was already open, ask them to restart it.
3. Run it again with `-Verify`. Success looks like `agent: Revit 2026 (build ...) pid ...: responding`.
   - If it says "No running Revit with the agent host", ask for pyRevit tab → Reload, then verify again. This can take a second reload.
4. Tell the user to restart the Claude desktop app and open a new Code session; the `pyrevit` MCP tools load only in new sessions. Suggest asking it "use the pyrevit tools to get the context of my open Revit model" as the first test.
5. Close with these points:
   - Every model change needs their **Keep/Discard** approval in Revit.
   - Anything the agent reads from the model is sent to the AI provider (see step 0), so only use it on projects where that's allowed.
   - Re-run this skill after any pyRevit update.

## House rules (all am-* skills)

- Write all output to the user in ASD-STE100 Simplified Technical English. Use short sentences (max 20 words for instructions, 25 for descriptions). Use active voice. Put one instruction in each sentence, and start it with the verb. Use one word for one meaning. Explain any technical term the first time you use it, because many users are architects, not programmers.
- When a task has independent parts (for example, several files to check or several Revit years to compare), do them in parallel with subagents. Keep steps that depend on each other in sequence.
- When the request is unclear, or there is more than one reasonable way to do it, ask before you act. Use the AskUserQuestion tool so the user can click an answer: ask one decision per question (max 4 questions at a time), give 2 to 4 short options, put your recommended option first with "(Recommended)" in its label, and give each option a one-line description of what it will do. Do not ask for facts you can find yourself (files, the Revit model through a read-only query, the docs). Never use a question in place of the Keep/Discard approval in Revit.

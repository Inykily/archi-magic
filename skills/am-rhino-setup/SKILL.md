---
name: am-rhino-setup
description: Connect Claude Code to Rhino 8 on Windows WITHOUT admin rights. Installs McNeel's official Rhino MCP plugin (Rhino-MCP-Platform) per-user with Yak, registers its router as the `rhino` MCP server in Claude Code, and adds permission rules so Claude must ask before every run_python, run_csharp or run_command call in Rhino. Use when the user asks to "set up Rhino", "connect Claude to Rhino", "install the Rhino MCP", "rhino mcp", "Rhino-MCP-Platform", "let Claude model in Rhino", or when the Rhino tools do not appear in Claude Code. NOT for Revit (use am-pyrevit7-setup).
---

# am-rhino-setup

Sets up McNeel's Rhino MCP Platform (https://mcneel.github.io/RhinoAI/docs/getting-started/cc-plugin/) for the current Windows user. The tested script `scripts/rhino-setup.ps1` in this skill's directory does all the work. **Run it, don't reimplement it.** Background, undo steps and the exit-code table are in `kit-README.md`.

An MCP server is a small program that gives Claude tools for another app. Here the tools read and change the open Rhino document.

## Rules

- The user has **no admin rights**. Never use elevation, UAC, `-Verb RunAs` or `yak install --all-users`.
- **Never start, close or kill Rhino yourself.** Ask the user to do it.
- Rhino has **no Keep/Discard approval** like the pyRevit agent. The only safety gate is the Claude Code permission prompt. Never remove or weaken the `permissions.ask` rules this script adds, and never suggest "don't ask again" as a fix.
- Rhino 8 is required. If the script reports Rhino 9 (WIP or BETA), ask with AskUserQuestion: "Rhino 8 (Recommended)" or "Rhino 9". Use `-RhinoVersion 9` only when the user picks it.
- Show the script's output, and explain every WARNING and every non-zero exit code.

## Steps

1. Check the current state (read-only):
   `powershell -NoProfile -ExecutionPolicy Bypass -File "<this skill dir>\scripts\rhino-setup.ps1" -Verify`
2. Run the full setup (install, connect, ask rules, verify):
   `powershell -NoProfile -ExecutionPolicy Bypass -File "<this skill dir>\scripts\rhino-setup.ps1"`
   - Exit code 3 means Yak could not install the plugin. Give the user the PackageManager steps that the script prints, and wait until they say it is done. Then run it again with `-Connect -Verify`.
   - Exit code 4 with "No router found" means Rhino has not loaded the plugin yet. Ask the user to open Rhino 8 once, then run `-Connect -Verify` again.
   - Exit code 5 means the settings file was not changed. Show the reason. Do not edit the file by hand unless the user asks.
3. Ask the user to open Rhino 8 (restart it if it was open) and to type `SetDotNetRuntime`. It must say **NETCore**. The plugin does not load on .NET Framework.
4. Tell the user to restart the Claude desktop app and open a new Code session. The `rhino` tools load only in new sessions. Suggest this first test: "use the rhino tools to list the objects in my open Rhino document".
5. Close with these points:
   - Claude asks before it runs Python, C# or a Rhino command in Rhino. Read each request before you approve it. Rhino has no Keep/Discard step, so use Undo in Rhino if a change is wrong.
   - Anything Claude reads from the model, and every viewport screenshot, goes to the AI provider. Use it only on projects where that is allowed.
   - If more than one Rhino window is open, Claude can edit a different document than the one you look at. Keep one Rhino open. If no Rhino is open, a Rhino tool call can start a new Rhino.
   - Save your file before you ask Claude to change it.

## House rules (all am-* skills)

- Write all output to the user in ASD-STE100 Simplified Technical English. Use short sentences (max 20 words for instructions, 25 for descriptions). Use active voice. Put one instruction in each sentence, and start it with the verb. Use one word for one meaning. Explain any technical term the first time you use it, because many users are architects, not programmers.
- When a task has independent parts (for example, several files to check or several Revit years to compare), do them in parallel with subagents. Keep steps that depend on each other in sequence.
- When the request is unclear, or there is more than one reasonable way to do it, ask before you act. Use the AskUserQuestion tool so the user can click an answer: ask one decision per question (max 4 questions at a time), give 2 to 4 short options, put your recommended option first with "(Recommended)" in its label, and give each option a one-line description of what it will do. Do not ask for facts you can find yourself (files, the Revit model through a read-only query, the docs). Never use a question in place of the Keep/Discard approval in Revit.

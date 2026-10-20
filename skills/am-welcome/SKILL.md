---
name: am-welcome
description: Introduce archi-magic to an architect who has never used a developer tool, a terminal or a programming language, and teach how to use it. Explains in plain words what archi-magic can do in Revit, builds a live "what you can ask -> what happens" table from the installed am-* skills, checks if pyRevit 7 and the Revit connection are already set up, gives a safe first-run path, and teaches how to ask well. Triggers on "what is archi-magic", "how do I use this", "help", "what can you do", "what can you do in Revit", "getting started", "I'm new", "teach me", "where do I start".
---

# am-welcome

Welcome a new user and teach them to use archi-magic. Assume the user is an architect with no software background. Do not dump everything at once. Give the short version, then let the user choose what to learn next.

## Step 1: Check the setup (read-only)

Run these checks before you talk. They do not change anything.

1. `Test-Path "$env:APPDATA\pyRevit-Master\bin\pyrevit.exe"` - True means pyRevit 7 is installed for this user.
2. `claude mcp get pyrevit` - a result that shows the server means Claude is connected to Revit. An error means it is not registered.
3. `powershell -NoProfile -ExecutionPolicy Bypass -File "<this skill dir>\scripts\list-skills.ps1"` - prints one `name<TAB>description` line for each installed am-* skill (am-welcome is not included).

4. Read the live agent policy. If the pyrevit MCP tools are in this session, call `get_context`; its result names the policy. If not, run `& "$env:APPDATA\pyRevit-Master\bin\pyrevit.exe" configs agent policy`; it prints `Agent policy: ask`, `readonly` or `auto`.

If a check fails or you cannot run it, treat that part as "not set up". Do not tell the user about the commands unless they ask.

## Step 2: Explain archi-magic in plain words

Say this in your own words, in 5 to 8 short sentences:

- archi-magic is a **plugin** for Claude. A plugin is a package that adds new skills to Claude.
- A **skill** is a set of instructions that teaches Claude one job. You do not type skill names. You ask in normal words, and Claude picks the correct skill.
- With the setup done, Claude can read your open **Revit model** (the building file that is open in Revit) and change it, but only when you approve.
- Give 3 or 4 examples from this list:
  - "Count all the doors on Level 2."
  - "Rename these sheets to our office standard."
  - "Find all walls that have no fire rating."
  - "Which Revit version added this feature?"
  - "List the rooms that have no number."
- Say that a 3D model viewer is coming soon. Do not promise a date.

Use [glossary.md](glossary.md) to explain a term in one plain sentence when the user meets it.

## Step 3: Show what you can ask

Build this table from the output of `list-skills.ps1`. **Do not use a fixed list.** Skills are added over time, and the script always shows the current set.

| What you can ask | What happens |
|---|---|

- Make one row for each line of output.
- Left column: one short example request in plain English, in quotation marks. Take it from the trigger phrases in the description when you can.
- Right column: one sentence, max 25 words, that says what Claude does. Do not use the skill name, file paths or programming terms.
- If the script fails, say "I cannot list the skills now." Then continue with Step 4.

## Step 4: Give the first-run path

Tailor the steps to the result of Step 1. Mark completed steps as "done" and skip them.

If the setup is not done, give this data warning **before** step 1. Do not wait until after the setup.

- Claude sends what it reads from the model to the AI provider. This includes element data, parameter values, pictures of views (screenshots), and project and file names.
- pyRevit keeps a plain-text record of each run in `%APPDATA%\pyRevit\agent` for up to 14 days. This folder is in your Roaming profile, so it can copy to your office servers.
- Claude keeps the chat records in `%USERPROFILE%\.claude\projects`.
- If you are not sure the project allows AI tools, ask your BIM manager first.

The setup skill asks the user to confirm this warning before it changes anything.

1. **Set up.** Type "set up pyRevit 7". This installs pyRevit 7 for your user account. You do not need admin rights. It takes about 2 minutes. Skip it if pyRevit 7 is installed and the `pyrevit` connection is registered.
2. **Open a model.** Start Revit and open a model. The Revit Home screen is not sufficient. An Autodesk sample model, for example *Snowdon Towers Sample Architectural*, is a good first choice.
3. **Ask a safe question first.** Ask a question that only reads the model, for example "How many rooms are on Level 1?" A question that only reads does not change the model.

Then tell the user about the two safety points:

- **Keep or Discard.** State the policy that you read in Step 1, check 4. Never assume it.
  - `ask`: When Claude wants to change the model, Revit shows the change and asks you. Click **Keep** to accept it. Click **Discard** to cancel it. Nothing changes until you click Keep.
  - `readonly`: Claude can only read the model. Claude cannot change it.
  - `auto`: Claude can change the model **without** asking you. Tell the user this clearly. Recommend the fix: type "set up pyRevit 7" to set the policy to `ask`. Do not change the policy yourself unless the user asks for it in the chat.
  - Unknown (the check failed): say "I cannot confirm that Revit asks you before each change." Do not promise Keep/Discard.
- **Data goes to the AI provider.** Claude sends what it reads (model data, pictures of views, project and file names) to the AI company. Use it only on projects where your office and your client permit this. If you are not sure, ask your BIM manager first.

## Step 5: Teach how to ask well

Give these tips as a short list:

- **Be specific.** Name the level, the category, the sheet or the view. "Doors on Level 2" is better than "the doors".
- **Ask for a preview first.** Say "Show me what you will change before you change it." This is a "dry run".
- **Make one change at a time.** Check each result before you ask for the next change.
- **Undo a change.** Click Discard before you keep a change. After you keep it, use Undo in Revit (Ctrl+Z).
- **Ask when you are not sure.** "What does this word mean?" is a good question.

## Step 6: Offer a menu

End with a short question. Do not continue until the user answers. Offer 3 or 4 choices, for example:

1. Set up the connection to Revit now.
2. Try a safe question on my open model.
3. Explain a word (show the glossary).
4. Show me what each skill can do.

Leave out a choice that does not apply. For example, leave out choice 1 if the setup is done.

## House rules (all am-* skills)

- Write all output to the user in ASD-STE100 Simplified Technical English. Use short sentences (max 20 words for instructions, 25 for descriptions). Use active voice. Put one instruction in each sentence, and start it with the verb. Use one word for one meaning. Explain any technical term the first time you use it, because many users are architects, not programmers.
- When a task has independent parts (for example, several files to check or several Revit years to compare), do them in parallel with subagents. Keep steps that depend on each other in sequence.
- When the request is unclear, or there is more than one reasonable way to do it, ask before you act. Use the AskUserQuestion tool so the user can click an answer: ask one decision per question (max 4 questions at a time), give 2 to 4 short options, put your recommended option first with "(Recommended)" in its label, and give each option a one-line description of what it will do. Do not ask for facts you can find yourself (files, the Revit model through a read-only query, the docs). Never use a question in place of the Keep/Discard approval in Revit.

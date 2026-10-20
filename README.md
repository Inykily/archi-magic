# archi-magic

Claude Code skills for architects working in Revit and the AEC toolchain. Every skill is prefixed `am-`.

## Install (once per machine)

In Claude Code (the Claude desktop app's Code tab, or the `claude` CLI):

```
/plugin marketplace add zsenarchitect/archi-magic
/plugin install archi-magic@archi-magic
```

This also installs two trusted general-purpose plugins, pinned to tested versions: [superpowers](https://github.com/obra/superpowers) (planning, debugging, test-driven development, code review) and Anthropic's [frontend-design](https://github.com/anthropics/claude-code/tree/main/plugins/frontend-design).

**Turn on auto-update once:** type `/plugin`, open the **Marketplaces** tab, select **archi-magic**, and choose **Enable auto-update**. Third-party marketplaces have it off by default. Without it, you get new skills only when you run `/plugin marketplace update archi-magic`.

Every release raises the plugin `version` (`scripts/bump-version.ps1`). Claude Code installs new content only when the version changes. `main` is protected: changes land through pull requests that must pass the `check` job, and that job fails when shipped content changes without a version bump.

## Skills

| Skill | What it does |
|---|---|
| `am-welcome` | Introduces archi-magic in plain words for architects who are new to these tools. It lists what you can ask, checks your setup, and gives a safe first-run path. To use it, ask Claude "what is archi-magic?" or "I'm new, help me start". |
| `am-pyrevit7-setup` | Installs pyRevit 7 per-user **without admin rights** and repoints Revit 2024–2026 to it, even when IT installed pyRevit 6.x machine-wide. It also enables the pyRevit Agent Runtime and connects it to Claude Code, so Claude can work with your open Revit model. To use it, ask Claude to "set up pyRevit 7". |
| `am-revit-api-docs` | Looks up the Revit API in the documentation installed with **your** Revit version, so code uses members that exist in your year. It can also compare years. Ask, for example, "does Revit 2024 have ElementId.Value?" |
| `am-pyrevit-docs` | Searches the official pyRevit documentation and the installed pyRevit source before Claude writes pyRevit tools. Ask, for example, "how do I show a table in the pyRevit output window?" |
| `am-grill-me` | Type `/am-grill-me` to have Claude interview you hard about a plan or design until nothing is left assumed. Adapted from Matt Pocock's MIT-licensed [skills](https://github.com/mattpocock/skills). |
| `am-grilling` | The interview method behind `am-grill-me`. It also starts when you say "grill me" about a plan, decision or idea. Adapted from Matt Pocock (MIT). |
| `am-bim-viewer` | Shows a Revit model in 3D in Claude Code. It exports the visible elements of the active view to JSON and builds an interactive viewer page. Use the Rhino mouse controls, click an element to see its BIM data, filter categories, and jump to Top, Front, Right or Perspective views. Install the `am-bim-viewer` mod for the `/bim-view` command. To use it, ask Claude to "show this model in 3D". |
| `am-schedule-view` | Shows a Revit schedule from your open model as Revit displays it, in an interactive table. You can search, sort, filter, copy as TSV, export CSV and compare two schedules or snapshots. It also shows the before/after preview for `am-safe-change`. Ask "show me the door schedule". |
| `am-safe-change` | Shows a before/after preview of any Revit model change and asks you to confirm before Revit changes. It then does a dry run, applies the change with your Keep/Discard in Revit, and checks the result. The first recipe is sheet renumbering. Ask, for example, "shift all sheet numbers from A301 up by one". |
| `am-model-health` | Checks the open Revit model without changing it: warnings, links, in-place families, rooms, duplicate Marks, CAD, views and file size. You get a short ranked report or an HTML dashboard with trends. Ask "check my model health". Adapted from [Utopia5327](https://github.com/Utopia5327/claude-plugin-for-revit-bim) (MIT). |
| `am-param-qa` | Finds elements whose required parameters are missing or empty (for example door Fire Rating, Mark, or your BEP list). Shows counts and a table, and can select the offenders in Revit. Ask "are my door parameters filled in?". Adapted from Utopia5327 (MIT). |
| `am-workset-audit` | Checks the worksets of your open team model: element counts, links and levels or grids on the wrong workset, and elements left on Workset1. It moves elements only after a dry run and your Keep/Discard in Revit. Ask Claude to "audit my worksets". Adapted from Utopia5327 (MIT). |
| `am-area-report` | Reports room areas by level and department, gross totals from area plans, and unplaced or unenclosed rooms. It can compare against a program you paste as CSV and save a CSV file. Ask Claude for "a room area report". Adapted from Utopia5327 (MIT). |
| `am-doctor` | Finds and fixes problems with pyRevit 7, the Revit connection and archi-magic. It checks your setup and recent logs, explains each problem, runs the fix you approve, and can draft a bug report. Ask Claude to "run the doctor" or say "Claude can't see my Revit model". |
| `am-revit-crash-doctor` | Finds out why Revit crashed or froze. It reads Revit journals, crash dumps, Autodesk crash reports and the Windows event log, then explains the likely cause and the next step. It only reads, and works with Revit closed. Ask Claude "Revit keeps crashing" or "why did Revit crash?" |

### Mods

A mod changes Claude Code itself (here: a slash command and a pane). Each mod is a separate plugin in this marketplace:

```
/plugin install am-bim-viewer@archi-magic
/plugin install am-schedule-view@archi-magic
```

| Mod | What it does |
|---|---|
| `am-bim-viewer` | Adds `/bim-view [model.json] [--open]`. It opens a BIM view pane in the session (a picture of the model with view, rotate, zoom and category buttons) and builds the interactive 3D viewer page for the Browser pane. With no file, it shows a demo model. It needs a Claude Code build with function hooks (tested on 2.1.299). |
| `am-schedule-view` | Adds `/am-schedule-view <file.json>`. It shows a schedule or an `am-safe-change` preview in a pane: a paged table with a filter box, schedule buttons, and Copy as TSV. The full interactive table opens in the Browser pane. Tested on 2.1.299. |

The pyRevit setup script also works without Claude. Run `skills/am-pyrevit7-setup/scripts/Setup-pyRevit7.cmd`. See [kit-README.md](skills/am-pyrevit7-setup/kit-README.md).

## Adding a skill

1. Create `skills/am-<name>/SKILL.md`. The frontmatter `name` must equal the folder name and start with `am-`.
2. Put helper scripts next to it, in `skills/am-<name>/scripts/`.
3. Add a row for the skill to the table above.
4. Run `scripts/sync-house-rules.ps1`. It copies `HOUSE-RULES.md` (output in ASD-STE100, subagents for parallel work, ask with clickable options when unclear) to the end of every `SKILL.md`. Edit the rules only in `HOUSE-RULES.md`.
5. Bump `version` in `.claude-plugin/plugin.json`, so installed copies pick up the update.

The `check` job (GitHub Actions) runs on every pull request and every push to `main`. `main` accepts changes only through pull requests that pass it. It runs:

- `scripts/check-skills.ps1`: fails if a skill folder lacks the `am-` prefix, if its `SKILL.md` name doesn't match the folder, if it's missing from the table above, or if its house rules differ from `HOUSE-RULES.md`.
- `scripts/check-version-bump.ps1`: fails if a changed file needs a version bump and the version did not go up. Every path needs a bump except repo-only files (README.md, LICENSE, docs/, .github/, .gitignore, .gitattributes and the repo scripts `scripts/check-*.ps1`, `bump-version.ps1`, `sync-house-rules.ps1`). A change under `mods/<name>/` also needs that mod's own version to go up.

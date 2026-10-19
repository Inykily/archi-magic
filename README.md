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

Every release raises the plugin `version` (`scripts/bump-version.ps1`). Claude Code installs new content only when the version changes, and CI blocks any push that changes plugin content without a bump.

## Skills

| Skill | What it does |
|---|---|
| `am-welcome` | Introduces archi-magic in plain words for architects who are new to these tools. It lists what you can ask, checks your setup, and gives a safe first-run path. To use it, ask Claude "what is archi-magic?" or "I'm new, help me start". |
| `am-pyrevit7-setup` | Installs pyRevit 7 per-user **without admin rights** and repoints Revit 2024–2026 to it, even when IT installed pyRevit 6.x machine-wide. It also enables the pyRevit Agent Runtime and connects it to Claude Code, so Claude can work with your open Revit model. To use it, ask Claude to "set up pyRevit 7". |
| `am-revit-api-docs` | Looks up the Revit API in the documentation installed with **your** Revit version, so code uses members that exist in your year. It can also compare years. Ask, for example, "does Revit 2024 have ElementId.Value?" |
| `am-pyrevit-docs` | Searches the official pyRevit documentation and the installed pyRevit source before Claude writes pyRevit tools. Ask, for example, "how do I show a table in the pyRevit output window?" |
| `am-grill-me` | Type `/am-grill-me` to have Claude interview you hard about a plan or design until nothing is left assumed. Adapted from Matt Pocock's MIT-licensed [skills](https://github.com/mattpocock/skills). |
| `am-grilling` | The interview method behind `am-grill-me`. It also starts when you say "grill me" about a plan, decision or idea. Adapted from Matt Pocock (MIT). |

The pyRevit setup script also works without Claude. Run `skills/am-pyrevit7-setup/scripts/Setup-pyRevit7.cmd`. See [kit-README.md](skills/am-pyrevit7-setup/kit-README.md).

## Adding a skill

1. Create `skills/am-<name>/SKILL.md`. The frontmatter `name` must equal the folder name and start with `am-`.
2. Put helper scripts next to it, in `skills/am-<name>/scripts/`.
3. Add a row for the skill to the table above.
4. Bump `version` in `.claude-plugin/plugin.json`, so installed copies pick up the update.

`scripts/check-skills.ps1` runs on every push (GitHub Actions). It fails if a skill folder lacks the `am-` prefix, if its `SKILL.md` name doesn't match the folder, or if it's missing from the table above.

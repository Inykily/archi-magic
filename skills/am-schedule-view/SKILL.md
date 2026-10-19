---
name: am-schedule-view
description: Use when the user wants to see/compare/export a Revit schedule from the open model - show a door, room, area, sheet or any schedule as Revit displays it, search/sort/filter it, copy it as TSV, export CSV, or compare two schedules or two snapshots of one schedule. Also renders the before/after change-preview table for am-safe-change. Read only. Triggers on "show me the door schedule", "open the room schedule", "export the area schedule to CSV", "compare these schedules", "what changed in the schedule". NOT for building new schedules (pyRevit 'scheduling' skill) or model QA (am-model-health).
---

# am-schedule-view

Shows Revit schedules in an interactive table page, exactly as Revit displays them. The cell text keeps Revit's own formatting, units, grouping rows and total rows.

Two scripts in this skill do the work. Run them; do not rewrite them.

| Script | Where it runs | What it does |
|---|---|---|
| `scripts/read_schedules.py` | Inside Revit, through the pyRevit agent, **query mode only** | Lists schedules, or reads chosen schedules to JSON. |
| `scripts/render-table.ps1` | On the user's computer | Turns schedule JSON or change-preview JSON into one self-contained HTML page. Can also write CSV files. |

## Steps

1. **Get the context.** Call the `pyrevit` MCP tool `get_context`. Confirm that a model is open. If no Revit responds, tell the user to run `am-pyrevit7-setup`.
2. **List the schedules.** Run `read_schedules.py` with `run_query` and no inputs (list mode). Pass the file text as `script`.
   - CLI alternative: `pyrevit agent run "<skill dir>\scripts\read_schedules.py" --mode=query --revit=<year>`.
   - The list gives name, category, kind, row count, and the sheets that show the schedule. Revision, keynote and panel schedules are skipped. Set `includeInternal: true` only when the user asks for them.
3. **Ask which schedule, if it is not clear.** Use AskUserQuestion. Put the most likely schedule first, with "(Recommended)". Prefer schedules that are on a sheet. Give up to 4 options.
4. **Read the schedules.** Run `read_schedules.py` again with inputs `{"mode": "read", "names": ["Door Schedule"]}`. You can also use `"ids": [510933]`. The default cap is 5000 rows for each schedule; `maxRows` changes it.
5. **Save the result on the user's side.** The result holds `payload`, an ASCII JSON string. Save the whole run record, or `result`, or the decoded payload to a `.json` file in the scratchpad. `render-table.ps1` accepts all three.
   - The script returns the data as one string because the agent's own JSON writer fails on non-ASCII text (for example "Cafe" with an accent).
   - If the immediate response is truncated, read the full run with `get_run` (CLI: `pyrevit agent show <run_id>`).
6. **Render the page.**
   `powershell -NoProfile -ExecutionPolicy Bypass -File "<skill dir>\scripts\render-table.ps1" -Json <file> -Out <page.html>`
   - Add `-CsvDir <folder>` to also write one CSV for each schedule (UTF-8 with BOM, so Excel opens it).
   - Add `-Json2 <later.json>` to compare two snapshots. The page labels the sets [A] and [B].
7. **Show the page.** Open it in the app's Browser pane (`preview_start` with the file URL, or `navigate`). If the pane shows a static snapshot of a local file, serve the folder on `127.0.0.1` and open that URL. Tell the user the file path, so they can open it in their own browser.
8. **Explain the result** in ASD-STE100: the schedule name, the row count, the group and total rows, and any cap note.

## What the page does

- Schedule picker with search. Each entry shows the category, the row count and an "On sheet" tag.
- Sticky column headings, including Revit's grouped headings ("Door", "Frame", "Size").
- Click a heading to sort (ascending, descending, Revit order). Feet-inch values and values with units sort as numbers. Group and total rows are hidden while sorted.
- Filter box, column show/hide switches, and a row count.
- Group rows and total rows have their own style. Number columns align right.
- "Copy as TSV" (paste into Excel) and "Export CSV" (a download in the browser). Nothing is exported from inside Revit.
- "Compare": pick two schedules or two snapshots and a column to match rows by. Added, removed and changed rows are marked. Changed cells show old and new values.
- Light and dark themes.

## Change preview (contract with am-safe-change)

`render-table.ps1` also renders a before/after preview. Input JSON:

```json
{ "kind": "change-preview", "title": "Shift sheets A301+ up by one", "keyColumn": "ElementId",
  "columns": ["ElementId", "Sheet Number", "Sheet Name"], "changedColumns": ["Sheet Number"],
  "before": [["1203406", "A301", "Building Sections"]], "after": [["1203406", "A302", "Building Sections"]],
  "notes": ["A301 is now free for the new sheet"], "warnings": [{"row": "1203406", "text": "..."}],
  "blocked": false, "params": {"start": "A301", "step": 1}, "steps": [[1203406, "A301", "A302"]] }
```

- Rows are matched by `keyColumn`. Changed cells show the old value struck through and the new value emphasized.
- The top shows counts (changed, unchanged, added, removed, warnings) and the status line "Preview only. Nothing in Revit has changed yet."
- Warnings are pinned at the top. A click on a warning scrolls to its row. Rows with a warning always show.
- Unchanged rows fold into "Show N unchanged". The default sort is the new value of the first changed column.
- `blocked: true` shows "Apply is blocked: resolve warnings first." `params` shows as an "Interpreted as" line. `steps` shows as an ordered list. Other keys are ignored.
- Sample: `assets/fixtures/change-preview.sample.json`.

## Rules

- **Query mode only.** Never use `run_modify`. Never change the active view or the selection. Do not use `capture_view` or `show_elements`, because they can change the view.
- If the agent answers `revit_busy`, another client uses Revit. Wait 20 to 30 seconds and try again, at most 8 times.
- Row kinds (`body`, `group`, `total`, `blank`) come from the table layout, because Revit has no API for them. The JSON says `rowKindSource: "heuristic"`. If a row looks wrong, say so.
- A cell shows the text Revit shows (`TableView.GetCellText`). This can differ from a parameter's own format. For example, the schedule shows "10219.89 SF" where the area parameter shows "10220 SF".
- Anything read from the model goes to the AI provider. Use this only on projects where that is allowed.
- The interactive page is a web page, not a panel inside Claude Code. The optional `am-schedule-view` mod adds a `/am-schedule-view` command and a pane with a short Markdown preview of the same JSON. See `mods/am-schedule-view/README.md`.

## House rules (all am-* skills)

- Write all output to the user in ASD-STE100 Simplified Technical English. Use short sentences (max 20 words for instructions, 25 for descriptions). Use active voice. Put one instruction in each sentence, and start it with the verb. Use one word for one meaning. Explain any technical term the first time you use it, because many users are architects, not programmers.
- When a task has independent parts (for example, several files to check or several Revit years to compare), do them in parallel with subagents. Keep steps that depend on each other in sequence.
- When the request is unclear, or there is more than one reasonable way to do it, ask before you act. Use the AskUserQuestion tool so the user can click an answer: ask one decision per question (max 4 questions at a time), give 2 to 4 short options, put your recommended option first with "(Recommended)" in its label, and give each option a one-line description of what it will do. Do not ask for facts you can find yourself (files, the Revit model through a read-only query, the docs). Never use a question in place of the Keep/Discard approval in Revit.

# am-schedule-view (mod)

A Claude Code mod for the `am-schedule-view` skill. It adds one slash command:

```
/am-schedule-view <path to .json>
```

The command opens a pane with the schedule (or the change preview) in the file. The pane shows one page of 25 rows as a table. It has schedule buttons, a filter field, Prev and Next, and "Copy as TSV".

The file comes from the skill: the output of `read_schedules.py`, or a `change-preview` file from `am-safe-change`. Ask Claude "show me the door schedule" to make one.

## Why a pane and a web page

A mod pane draws only the engine's own elements (`Box`, `Text`, `Button`, `Input`, `Markdown` and a few more). It has no HTML. So the full interactive table (sort, column hide, compare, CSV export) is a web page that `skills/am-schedule-view/scripts/render-table.ps1` makes. Claude opens that page in the app's Browser pane. This mod is the quick view inside the session.

## Limits

- The pane reads files up to 4 MB, and keeps the first 2000 rows of each table.
- Sorting and compare are only in the web page.

## Install

```
/plugin install am-schedule-view --marketplace zsenarchitect/archi-magic
```

If the archi-magic marketplace is already added: `/plugin install am-schedule-view@archi-magic`.

## Develop

- `claude plugin validate mods/am-schedule-view`
- `claude plugin test mods/am-schedule-view`

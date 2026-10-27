# Recipe: sheet renumbering

Example request: "Shift all sheet numbers from A301 onward up by one, so I can insert a new sheet at A301."

Files (paths relative to the am-safe-change skill folder):

| Step | File | Where it runs |
|---|---|---|
| 3 Read | `scripts/read_sheets.py` | Revit, `run_query` |
| 4 Compute | `scripts/sheet_preview.py compute` (uses `scripts/lib/sheet_shift.py`) | Terminal, CPython 3 |
| 7 Execute | `scripts/apply_sheet_shift.py` | Revit, `run_modify` (dry run, then real) |
| 7, 8 Compare | `scripts/sheet_preview.py compare` | Terminal, CPython 3 |

## Step 2: questions to ask

Ask only the questions that the request leaves open. Use AskUserQuestion, one decision per question:

1. **Which sheets move?**
   - Only the A3xx series from A301 up (Recommended): A301 to A399 move. A401 and higher stay.
   - Every sheet with prefix A from A301 up: A3xx, A4xx, A5xx and higher all move.
   - A custom list: the user names the sheets.
2. **Suffixed numbers (A301a, A301.1)?**
   - Move with their base number (Recommended): A301a becomes A302a.
   - Leave them as they are.
3. **Gaps in the series (for example A301, A302, A305)?**
   - Keep the gaps (Recommended): every number goes up by 1. The result is A302, A303, A306.
   - Close the gaps: the numbers become consecutive. The result is A302, A303, A304.
4. **Placeholder sheets** (sheets in the sheet list with no drawing yet)?
   - Move them like other sheets (Recommended).
   - Leave them. A placeholder still holds its number, so it can block a move.

Then say the scope back in one sentence, for example: "I will add 1 to sheets A301 to A307 in the A3xx series, keep the gaps, and move suffixed and placeholder sheets too."

## Step 3: read

`run_query` with the content of `scripts/read_sheets.py`. Save the JSON result as `read.json`. The result has every sheet: `id`, `number`, `name`, `placeholder`.

## Step 4: compute

```powershell
python "<skill dir>\scripts\sheet_preview.py" compute --read read.json --start A301 --out preview.json
```

Options: `--step -1` (shift down), `--scope after` or `--scope custom --ids 123,456`, `--close-gaps`, `--no-suffixed`, `--no-placeholders`, `--title "..."`. The command prints the chat table. Exit code 1 means the preview is BLOCKED.

How the computation works (`scripts/lib/sheet_shift.py`):

- A number is split into a prefix, digits and a suffix: `A301a` is `A` + `301` + `a`. The new number keeps the zero padding (`A-009` becomes `A-010`) and the suffix.
- Sheet numbers must be unique in a Revit document. Revit rejects `A302` while another sheet still has `A302`. So the steps are ordered. For an upward shift, the highest number moves first (A307 to A308, then A306 to A307, and so on). For a downward shift (negative step), the lowest number moves first (A302 to A301, then A303 to A302, and so on). Neither order needs temporary numbers.
- If that order cannot work (possible when you close gaps), the steps go through temporary numbers `TMP-AMSC-<id>` in the same transaction. Revit does not allow `~` and some other characters in a sheet number, so the temporary prefix does not use them.
- The compute step replays every step on a copy of the numbers. It stops if any step would reuse a number that is still in use.
- Blocking warnings (Apply is not allowed):
  - A new number is already used by a sheet that does not move. Example: A399 to A400 when A400 exists. Placeholders count.
  - Two sheets get the same new number.
  - A new number contains a character that Revit rejects.
- Other warnings: a number gets one more digit (A999 to A1000), a number leaves its series (A399 to A400), or a placeholder sheet moves.
- Number checks ignore upper and lower case. This is the safe side.

## Step 7: execute

1. `run_modify` with `dry_run: true`, the content of `scripts/apply_sheet_shift.py`, and `inputs: {"preview_path": "<full path to preview.json>"}`. Save the result as `dryrun.json`.
2. Compare:
   `python "<skill dir>\scripts\sheet_preview.py" compare --preview preview.json --actual dryrun.json`
   It must print `MATCHES PREVIEW`. If it prints `DIFFERENT`, stop.
3. Show the side-effect counts:
   `python "<skill dir>\scripts\sheet_preview.py" side-effects --preview preview.json --dryrun dryrun.json`
   Show the two numbers in chat: sheets the script edited on purpose, and dependent elements Revit regenerated (views on the sheets show the new number, so they redraw). Say in one sentence why dependents change (the command prints it). If the command warns about an unexpected category, tell the user and ask whether to continue before you apply.
4. `run_modify` with the same script and inputs, without dry run. The user clicks Keep or Discard in Revit.

The apply script first checks that every sheet still has its "before" number and that no sheet was added. Then it replays the preview's `steps` in one transaction. It returns the number of every sheet after the steps.

A sheet number change also changes the sheet-number value that views on the sheet show. So the change set in Revit lists more elements than the number of sheets. In the Snowdon Towers sample, 7 sheets changed 34 elements.

## Step 8: verify

Run `read_sheets.py` again, save it as `verify.json`, then:
`python "<skill dir>\scripts\sheet_preview.py" compare --preview preview.json --actual verify.json`

## Tests

`python -m pytest "<skill dir>\tests" -q`, or `python "<skill dir>\tests\test_sheet_shift.py"` without pytest.

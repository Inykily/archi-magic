# Recipe: flag instances in a QA parameter

Example request: "Flag the walls that are taller than their type's limiting height."

This recipe writes a short value to a text parameter of each instance that fails a check. The team can then filter, schedule or tag the flagged instances. It comes from issue #250.

Files (paths relative to the am-safe-change skill folder):

| Step | File | Where it runs |
|---|---|---|
| 3 Read | `scripts/read_instance_flag.py` | Revit, `run_query` |
| 4 Compute | `scripts/instance_flag_preview.py compute` (uses `scripts/lib/instance_flag.py`) | Terminal |
| 7 Execute | `scripts/apply_instance_flag.py` | Revit, `run_modify` (dry run, then real) |
| 7 Compare | `scripts/instance_flag_preview.py compare` | Terminal |
| 8 Verify | `scripts/read_values_by_id.py`, then `scripts/verify_commit.py` | Revit, then terminal |

## The value

`<FLAG> +<amount> @<YYYY-MM-DD HH:MM>`, for example `OVER +0.75 @2026-11-18 14:30`.

- Keep it short. The user asked for this compact form in the field report. Do not add the limit, the type, the mark or the phase. The model has them.
- The run time is part of the value. The value is a snapshot. It can be wrong a few days later. The time tells a reader how far to trust it.
- Every re-run clears the values of older runs on elements that now pass. A value is "ours" when it has the form above. The recipe never changes other text. Other text in the parameter blocks the preview.

## Step 2: questions to ask

1. **Which check?** The categories, the instance value and the limit, for example Walls, "Unconnected Height", and the type parameter "Limiting Height".
2. **Which parameter?** The name of the QA text parameter. If it does not exist, the apply script creates it (see "The parameter").
3. **Which flag word and unit?** For example `OVER`, in feet with 2 decimals (Recommended), or inches (`--scale 12 --unit " in"`), or millimetres (`--scale 304.8 --unit " mm" --decimals 0`).

If the task compares two fields or two sources (for example a type name code and a Type Mark), ask which one is the source of truth before you compute. See step 2 of the skill.

## Step 3: read

`run_query` with `scripts/read_instance_flag.py` and inputs such as:

```json
{"categories": ["OST_Walls"], "parameter": "QA Flag",
 "value_parameter": "Unconnected Height", "limit_parameter": "Limiting Height", "limit_on": "type"}
```

It returns each instance with its amount (value minus limit, in feet, or null when it passes), the current flag value, its ownership status and whether it is in a group. Save it as `read.json`. Elements with no value or no limit get `check: "no value"` or `"no limit"`. List them for the user.

## Step 4: compute

`python scripts/instance_flag_preview.py compute --read read.json --flag OVER --run-time "2026-11-18 14:30" --out preview.json`

Use the current local time for `--run-time`. The command prints the chat table and the counts: set, cleared, unchanged, skipped. Exit code 1 means BLOCKED.

- An element that another user borrows (`OwnedByOtherUser`) is skipped. The preview lists it with its owner. Tell the user. Never take an element from its owner.
- Then do the ownership check of step 4 of the skill. The preview has `ownership_ids`.

## The parameter

The Revit API cannot make a plain project parameter. When the parameter does not exist, `apply_instance_flag.py` does this in the same transaction:

1. It writes an empty temporary shared parameter file in the temp folder.
2. It points `Application.SharedParametersFilename` at that file, creates a text definition in the group `am-safe-change`, and binds it as an instance parameter to the preview's categories, in the Data group.
3. It sets "values can vary by group instance" (`SetAllowVaryBetweenGroups`), so instances in groups can hold different values.
4. In a `finally` block it restores the user's `SharedParametersFilename` and deletes the temporary file. This also happens in a dry run and when the run fails.

The result has `shared_parameter_file_restored`. The `compare` command stops when it is false and prints the old path. Tell the user the old path, so they can set it again in **Manage > Shared Parameters**.

## Step 7: execute

1. `run_modify` with `dry_run: true`, the content of `scripts/apply_instance_flag.py` and `inputs: {"preview_path": "<full path to preview.json>"}`. Save the result as `dryrun.json`.
2. `python scripts/instance_flag_preview.py compare --preview preview.json --actual dryrun.json`. It must print `MATCHES PREVIEW`.
3. Read the change list: `python scripts/dry_run_checks.py change-list --preview preview.json --dryrun dryrun.json`. Expect only the flagged categories. A new parameter also changes "Shared Parameters" or "Project Parameters" elements. Name them to the user.
4. Run the same script without dry run. The user clicks Keep or Discard.

The apply script stops with "Model changed since the preview" when a value changed, when the parameter appeared or went away, or when another user now borrows a target.

## Step 8: verify

Run `scripts/read_values_by_id.py` with `inputs: {"preview_path": "<preview.json>"}`. Then `python scripts/verify_commit.py --preview preview.json --reread reread.json --run run.json`. Put its first line in the summary.

## Re-run procedure

Give the user these steps in the summary, so that a later session can repeat the check:

1. Run the read with the same inputs.
2. Compute with a new run time. Older flags on passing elements are cleared.
3. Dry run, compare, Keep.

## A note in the model is a handoff

When the user asks for a note in the model (a text note on a sheet or a drafting view) about this work, write it for the next person or agent, not as a task list. Use these parts:

- **Why**: the reason for the check.
- **Rules**: each rule with its reason, for example "the type name is the source of truth, because the legend uses it".
- **How to re-run**: the steps above, with the parameter, the flag word and the inputs.
- **Done**: what this run changed, with the run time.
- **To do**: what is still open, for example the skipped elements and their owners.

The note is a model change too. Show its text in the preview and add it through the same dry run and Keep.

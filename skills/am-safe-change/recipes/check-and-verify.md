# Recipe: check the dry run content, read the change list, verify after the commit

This recipe adds content checks to steps 7 and 8 of every change. Use it for every recipe, and for a change with no recipe. It comes from issues #256 and #255.

Counts alone did not find these defects. Each one passed a dry run and was committed:

- New elements about two storeys above their level. They did not show in the plan.
- 118 keynote tags with empty text.
- 70 copied tags that kept the leader end of the template tag.
- Floor areas read before `doc.Regenerate()`. They read 0.0, and the report said "correct".
- 87 modified keynote tags and some uncategorized elements, called "regeneration" with no check.
- A run with decision `committed` and an Error in `failures`. Nobody read the model again.

Files (paths relative to the am-safe-change skill folder):

| Step | File | Where it runs |
|---|---|---|
| 7 Collect content | `scripts/dry_run_content.py` (import it in the apply script) | Revit, `run_modify` dry run |
| 7 Check content | `scripts/dry_run_checks.py content` | Terminal |
| 7 Read the change list | `scripts/dry_run_checks.py change-list`, `annotation-text` | Terminal |
| 7, 8 Errors in failures | `scripts/dry_run_checks.py failures` | Terminal |
| 7, 8 Read by id | `scripts/read_values_by_id.py` | Revit, `run_query` |
| 8 Verify | `scripts/verify_commit.py` | Terminal |

The pure checks are in `scripts/lib/run_checks.py` and `scripts/lib/commit_verify.py`.

## 1. Content checks in the dry run

The apply script returns a `content` object in its result. Build it at the end of the transaction, before the script commits:

```python
import dry_run_content   # run_modify "workspace" = the skill's scripts folder
content = dry_run_content.collect(doc, target_view_id, new_ids,
                                  tag_ids=extra_tag_ids,
                                  value_reads=[(floor_id, "Area")])
result = {"rows": rows, "content": content}
```

- `target_view_id` is the view the user will look at. Use its id. Do not use `doc.ActiveView`. After a view change, the active view can be a sheet.
- `collect()` calls `doc.Regenerate()` first. Read area, length and volume only after that call.
- It reads only. It changes nothing.

Save the dry run as `dryrun.json`. Then run:

`python scripts/dry_run_checks.py content --dryrun dryrun.json`

It gives one warning for each problem:

- A new element is outside the view range of the target plan (below the view depth or above the top clip plane), outside its crop region, or hidden in the view.
- A new tag or text note has empty text, or Revit's "?".
- A leader ends more than 3 ft (in plan) from its host. Change the limit with `--max-leader-ft`.
- Two or more tags of different hosts share one leader end. A copied tag kept the leader end of its template.
- A computed value reads 0 or nothing. A value read before `doc.Regenerate()` is a stop.

Exit code 1 means a warning or a stop. Show every line to the user. Do not apply until the user answers. Fix the script and run the dry run again when you can.

## 2. Read the change list

Every dry run lists the changed elements by category. Read it. Do not call it "regeneration" without a check.

1. Put the categories the plan edits in the preview as `edited_categories`. Put the categories that can change as a side effect in `expected_dependent_categories`.
2. Run: `python scripts/dry_run_checks.py change-list --preview preview.json --dryrun dryrun.json`
3. A category that the preview does not expect is a stop. So are uncategorized elements, unless the preview lists `"(no category)"`. Read the class and the owner view of each one. Tell the user what they are. Ask before you apply.
4. Name every changed tag or annotation, with its text before and after:
   1. Run `scripts/read_values_by_id.py` with `run_query`, the annotation ids from step 2, and `"parameters": ["Category", "Text"]`. Save it as `before.json`. This is the text now.
   2. Run the apply script again as a dry run. Pass the same ids as `tag_ids` to `collect()`. Save it as `dryrun2.json`. This is the text after the change. The dry run rolls back.
   3. `python scripts/dry_run_checks.py annotation-text --before before.json --after dryrun2.json --out annotations.json`
   4. `python scripts/dry_run_checks.py change-list --preview preview.json --dryrun dryrun.json --annotations annotations.json`
5. Show the table of annotations to the user. Mark each text that changes, and each text that becomes empty.

## 3. Errors in failures

The run record has a `failures` list. An entry with severity Error is a stop, also when the decision is `committed` (issue #255). Example: "You now own the element, but your file is out of date. You must Reload Latest before editing the element." The edit may not be in the model.

`python scripts/dry_run_checks.py failures --run run.json`

Exit code 1 means an Error. Do not report the change as done. Read the model again (section 4) and tell the user what you found. For "Reload Latest", tell the user to click **Collaborate > Reload Latest**, then start again at step 3 of the skill.

## 4. Verify after the commit

After Keep (or after a commit under policy `auto`):

1. Run `scripts/read_values_by_id.py` with `run_query` and `inputs: {"preview_path": "<preview.json>"}`. It reads every preview row and every planned deletion by element id, with the preview's columns. Save it as `reread.json`. For a recipe with its own read script and `compare` command, you can use those instead.
2. Run: `python scripts/verify_commit.py --preview preview.json --reread reread.json --run run.json`
   - `--run` is the saved record of the real run. Its decision must be `committed`, with no Error in `failures`.
3. Copy its first line into the final summary. Every final summary has one of these lines:
   - `Verified by re-read: 23 of 23 elements match the preview (by element id).`
   - `Not verified: 2 of 23 elements differ from the preview; 1 not found by id.`
4. Never write "done" from the script's own counts. "Still the old value" means the change did not reach that element.
5. An element that is "not found by id" can have a new id after a sync or a reload. Find it by level and location, not by the saved id. Then tell the user.

`verify_commit.py` needs the key column `ElementId` in the preview. Exit code 0 means verified, 1 means not verified, 2 means bad input.

## 5. Probes stay dry runs

A probe is a test run that finds out what the API does, for example "can I make a keynote tag on this element?". Run every probe with `dry_run: true`. Never commit a test element. In the field report, two empty probe tags were committed, and a later commit had to delete them. When the probe answers the question, build the real preview and start at step 5 of the skill.

## 6. Do not guess the cause of drift

When the model differs from the baseline, do not say "a teammate changed it" without evidence. Read the last-changed-by user of the element first (`WorksharingUtils.GetWorksharingTooltipInfo(doc, id).LastChangedBy`). Show it with the difference.

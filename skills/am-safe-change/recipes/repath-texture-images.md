# Recipe: repath texture images (appearance assets)

Example request: "Find the materials with missing texture images, and repath what you can to the ACC Desktop Connector folder."

Files (paths relative to the am-safe-change skill folder, except the read script, which lives in am-material-audit):

| Step | File | Where it runs |
|---|---|---|
| 3 Read | `..\am-material-audit\scripts\read_texture_paths.py` | Revit, `run_query` |
| 3 Audit | `..\am-material-audit\scripts\texture_report.py` | Terminal, CPython 3 |
| 4 Compute | `scripts/texture_repath_preview.py compute` (uses `scripts/lib/texture_repath.py`) | Terminal, CPython 3 |
| 4 Ownership | `scripts/ownership.py` + `scripts/read_ownership.py` | Terminal + Revit, `run_query` |
| 7 Execute | `scripts/apply_texture_repath.py` | Revit, `run_modify` (dry run, then real) |
| 7 Side effects | `scripts/texture_repath_preview.py side-effects` (uses `scripts/lib/side_effects.py`) | Terminal, CPython 3 |
| 7 Compare dry run | `scripts/texture_repath_preview.py compare-dryrun` | Terminal, CPython 3 |
| 8 Compare | `scripts/texture_repath_preview.py compare` | Terminal, CPython 3 |
| Hand-off | `assets/missing-images-note.md` | Chat, by hand |

## Step 2: questions to ask

Ask only the questions that the request leaves open. Use AskUserQuestion, one decision per question:

1. **Which materials?**
   - Every material in the model (Recommended): the audit covers all appearance assets.
   - One name group, for example "Floor Finish": the read takes a prefix.
2. **Where do the replacement files live?**
   - This project's ACC Desktop Connector folder (Recommended): the compute scans that folder only, never another project's folder.
   - Another folder the user names: the compute scans that folder only.
3. **Loose matches?**
   - Propose them with a warning (Recommended): a file with the same name but a different extension (for example `.jpg` vs `.png`) is proposed, and the preview flags it for a human check.
   - Leave them out: only exact file-name matches are proposed.

Then say the scope back in one sentence, for example: "I will audit every material's texture paths, repath the missing ones from this project's ACC folder, and list the rest for their owners."

## Step 3: read, then audit

1. `run_query` with the content of `..\am-material-audit\scripts\read_texture_paths.py`. Input: `{"prefix": ""}` for every material, or `{"prefix": "<name group>"}` for one group. Save the JSON result as `read.json`.
2. Classify the slots:
   ```powershell
   python "<am-material-audit dir>\scripts\texture_report.py" --read read.json --out audit.json
   ```
   Add `--library-dir <folder>` when the Autodesk library lives somewhere other than the two Program Files homes. The audit reports each slot as `ok`, `ok_in_autodesk_library` (resolved by file name in the installed library), `file_not_found`, `empty_path`, or lists the material under unreadable assets. A stored path under the (x86) Program Files home still counts as `ok_in_autodesk_library` when the library is installed under plain Program Files: Revit finds a library texture by file name alone.
3. Say the audit counts first: materials, slots, ok, ok in library, missing, empty, unreadable. Say the caveats: bare file names are resolved only against the installed library, not against Revit's "Additional render appearance paths" option; empty bitmap slots (most often the pattern and perforation slots of metal and plastic assets) are probably unused defaults; assets that read as empty are most often built-in system and analytical materials, and the reason is not known.

## Step 4: compute, then check ownership

1. Compute the preview from the audit and the search folder:
   ```powershell
   python "<skill dir>\scripts\texture_repath_preview.py" compute --read audit.json --folder "<project folder>" --out preview.json
   ```
   The command prints the chat table. The preview has one row per material (so the user sees every material fixed) and one step per (asset, slot) (so one asset edit fixes every material that shares it). Only `file_not_found` slots are candidates. A loose match carries a non-blocking warning. A slot with two or more same-name files gets no proposal and is listed under `needs_choice`. A slot with no file at all is listed under `not_found` for the hand-off note.
2. Check ownership (step 4 of the skill). The preview's `ownership_ids` are the appearance asset element ids the apply script edits. A blocked element stops the run before the preview, as usual.

## Step 5: preview

Show the preview two ways, as usual (web page plus chat table). The chat table shows the first 10 and last 10 changed rows, the counts (changed, unchanged, warnings), every warning, and the ownership line. Name the loose matches one by one: each one needs a human check, and the user's approval of the preview is that check. Name the `not_found` count and the `needs_choice` count. If the preview has a blocking warning (materials on one asset disagree on the stored path), do not offer Apply: explain it and offer Change scope or Cancel.

## Step 7: execute

1. `run_modify` with `dry_run: true`, the content of `scripts/apply_texture_repath.py`, and `inputs: {"preview_path": "<full path to preview.json>"}`. Save the result as `dryrun.json`.
2. Compare the dry run against the preview:
   `python "<skill dir>\scripts\texture_repath_preview.py" compare-dryrun --preview preview.json --actual dryrun.json`
   It must print `MATCHES PREVIEW`. If it prints `DIFFERENT`, stop.
3. Show the side-effect counts:
   `python "<skill dir>\scripts\texture_repath_preview.py" side-effects --preview preview.json --dryrun dryrun.json`
   Show the two numbers in chat: elements the script edited on purpose, and dependent elements Revit regenerated. The expected dependent categories are Materials, Views, Keynote Tags and Legends (the same set the material-colors recipe treats as expected for material changes). If the command warns about an unexpected category, tell the user and ask whether to continue before you apply.
4. `run_modify` with the same script and inputs, without dry run. The user clicks Keep or Discard in Revit.

The apply script first checks that every slot still holds its "before" path. Then, in one transaction, it opens one `AppearanceAssetEditScope` per asset, gets the editable asset, finds the bitmap string property for the slot, checks `IsValidValue` for the new path, sets `Value`, and commits the scope. It returns the values of each slot after the change.

## Step 8: verify

Run `read_texture_paths.py` again, save it as `verify-read.json`, classify it with `texture_report.py` into `verify.json`, then:
`python "<skill dir>\scripts\texture_repath_preview.py" compare --preview preview.json --actual verify.json`

It must print `MATCHES PREVIEW`: every target slot shows the new path. Then end with the "Sync to Central hand-off" from the skill.

## Missing-images note (hand-off, optional)

For the slots that no file covers, build the note from `assets/missing-images-note.md`: the files grouped by the owner of each stored path, the upload folder, and a "fixed tonight" line. The agent writes the note text; the user places it in the model's "save to central" drafting view. The note is text only: no script writes to the model for this step.

## Tests

`python -m pytest "<skill dir>\tests\test_texture_repath.py" -q`, or `python "<skill dir>\tests\test_texture_repath.py"` without pytest.

## Not verified on a live model

The Revit-side walk (connected properties, `GetRenderingAsset`, `AppearanceAssetEditScope`) follows issue #90, which ran this pattern live on Revit 2026. This sandbox has no Revit, so the walk is verified by code review only. The recipe's own dry run is the check that it holds on the user's Revit version: if the dry run fails, stop and report before any real change.

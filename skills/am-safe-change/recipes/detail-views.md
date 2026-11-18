# Recipe: detail views on a sheet

Example request: "Add two floor-transition section details to sheet A401, next to Detail 21, and match the existing viewports."

This recipe covers the field report in issue #50. A plain `Viewport.Create` leaves odd label settings and lands off the requested point. The next free detail number breaks the sheet's own pattern. This recipe copies the label settings, centers the box, and proposes numbers in the sheet pattern.

Files (paths relative to the am-safe-change skill folder):

| Step | File | Where it runs |
|---|---|---|
| 3 Read | `scripts/read_detail_views.py` | Revit, `run_query` |
| 4 Compute | `scripts/detail_preview.py compute` (uses `scripts/lib/detail_views.py`) | Terminal, CPython 3 |
| 7 Execute | `scripts/apply_detail_views.py` | Revit, `run_modify` (dry run, then real) |
| 7, 8 Compare | `scripts/detail_preview.py compare` | Terminal, CPython 3 |
| New section: read markers | `scripts/read_section_markers.py` | Revit, `run_query` |
| New section: plan cuts | `scripts/section_mark_plan.py plan` (uses `scripts/lib/section_marks.py`) | Terminal |

Scope: each new detail copies the crop box and the view template from an existing section view. For a brand-new section at a mark on a plan (for example from a reviewer's PDF markup), use "New section from a markup" below.

Look direction (issue #257): `ViewSection.CreateDetail` reads the box `BasisZ` as the look-into direction. A view's `CropBox.BasisZ` points the other way, towards the viewer (the same as `View.ViewDirection`). `apply_detail_views.py` therefore turns the source crop box 180 degrees about its up axis before `CreateDetail` (same world volume), and stops when the new view's `ViewDirection` differs from the source's. The result lists both directions under `directions`.

## Step 2: questions to ask

Ask only the questions that the request leaves open. Use AskUserQuestion, one decision per question:

1. **Which sheet?**
   - The sheet the user names. Name it back in the scope sentence.
2. **Which viewport is the reference?**
   - The viewport the new ones must match (Recommended): the closest existing viewport on the same sheet. The recipe copies its label offset, label line length, and viewport type.
   - Another viewport the user names.
3. **Which section does each new detail copy?**
   - The user names one source section per new detail. The new detail copies its crop box and view template.
4. **Where does each new viewport go?**
   - The user gives the requested box center on the sheet, in feet. Or: next to a named viewport, and you read that viewport's box center and propose a point beside it.
5. **Detail numbers?**
   - Use the proposed pattern numbers (Recommended): the compute step proposes them from the sheet's existing numbers. See "How the numbering works" below.
   - The user names the numbers.

Then say the scope back in one sentence, for example: "I will add 2 detail views to sheet A401, copy Detail 21's label settings, and number them 22 and 30."

Keynote tags: tell the user one limit before the preview. Revit cannot place a material keynote tag on a cut floor layer. See "Keynote tags" below. The preview uses text notes for keynotes when the user asks for them.

## Step 3: read

`run_query` with the content of `scripts/read_detail_views.py`. Use `inputs: {"sheet_id": <id>}` to read one sheet, or no inputs to read all sheets. Save the JSON result as `read.json`. The result has every sheet with its viewports (detail number, viewport type, label offset, label line length, box center) and every section view that can serve as a source.

## Step 4: compute

```powershell
python "<skill dir>\scripts\detail_preview.py" compute --read read.json --sheet 100 --reference 1 --detail "North transition:7.5:2.0:50" --detail "South transition:7.5:4.0:51" --out preview.json
```

Each `--detail` value is `"name:x:y:source_view_id"`. x and y are the requested box center on the sheet, in feet. The command prints the chat table. Exit code 1 means the preview is BLOCKED.

How the computation works (`scripts/lib/detail_views.py`):

- Label settings: every new viewport copies `LabelOffset` and `LabelLineLength` from the reference viewport, and its viewport type from the same reference. A plain `Viewport.Create` followed by `ChangeTypeId` left offset near -1.16 ft and line length near 0.26 ft in the field report. The existing viewports had offset (0.01, 0.01) and line length 0.81.
- Box center: the apply script calls `SetBoxCenter` with the requested point after `Viewport.Create`. A plain `Create` landed about 1.4 ft from the requested center. The verify step re-reads the box center and compares it with the preview.
- How the numbering works: the first new number continues the highest run (max + 1). Each later new number starts the next decade (the smallest multiple of 10 above the previous proposal). Example: existing numbers 10-12, 20-21, two new details, give 22 and 30. This rule is a proposal, not a fact about the sheet. The preview always shows it. The user can change it in step 6.
- Blocking warnings (Apply is not allowed):
  - The reference viewport is not on the target sheet.
  - The reference viewport has no label settings or no viewport type to copy.
  - A source section is not in the read result.
  - A proposed detail number is already used on the sheet.
- Other warnings: a detail number on the sheet is not an integer, so the compute step skips it.

## Step 7: execute

1. `run_modify` with `dry_run: true`, the content of `scripts/apply_detail_views.py`, and `inputs: {"preview_path": "<full path to preview.json>"}`. Save the result as `dryrun.json`.
2. Compare:
   `python "<skill dir>\scripts\detail_preview.py" compare --preview preview.json --actual dryrun.json`
   It must print `MATCHES PREVIEW`. If it prints `DIFFERENT`, stop.
3. Show the side-effect counts:
   `python "<skill dir>\scripts\detail_preview.py" side-effects --preview preview.json --dryrun dryrun.json`
   Show the two numbers in chat: viewports the script created on purpose, and dependent elements Revit regenerated (new views and their viewports). Say in one sentence why dependents change (the command prints it). If the command warns about an unexpected category, tell the user and ask whether to continue before you apply.
4. `run_modify` with the same script and inputs, without dry run. The user clicks Keep or Discard in Revit.

The apply script first checks that the sheet still exists, that the reference viewport still has the preview's label settings, and that every proposed detail number is still free. Then it replays the preview's `steps` in one transaction. It returns the values of every new viewport after the steps, re-read after `SetBoxCenter`.

## Step 8: verify

Run `read_detail_views.py` again, save it as `verify.json`, then:
`python "<skill dir>\scripts\detail_preview.py" compare --preview preview.json --actual verify.json`

Capture check: when you capture a view to show the user, check that the cut geometry is present. `capture_view` sometimes returns a section with the cut geometry missing, then returns it correctly on the next call. This looks like a regen timing issue after a commit. If the capture misses the cut geometry, wait a few seconds and capture again. Do not report the first capture as the result.

## New section from a markup

Use this path when the user marks new cuts on a plan, for example in a PDF markup or a screenshot, and no section exists there yet. It comes from issue #257: about 20 new detail sections from one markup.

1. **Read the marks.** Use `am-markup-intake`. A flattened PDF has no annotations, so the marks are found by color (see its "Flattened PDF" section). For each section mark, write a name, the two ends of the cut line in model coordinates (feet), and one point on the thick bar or the arrow (`bar_side`). The look direction is towards the bar side. Reviewers often draw the head and the tail mirrored, so the bar side decides, not the order of the ends. When a position comes from an image, it is an estimate. Snap it to a model edge when you can (for example a floor sketch edge near the mark), and say so.
2. **Check your first guess.** Colored marks on a PDF are usually the reviewer's, not model markers. Read the model before you assume a mark is an existing marker. A view filter in the plan template can hide existing markers.
3. **Read the existing markers.** Run `scripts/read_section_markers.py` with `run_query`. Save the result as `markers.json`. It lists the cut line of every section and detail view.
4. **Plan the cuts and remove duplicates.** Never cut the same spot twice.

   ```powershell
   python "<skill dir>\scripts\section_mark_plan.py" plan --marks marks.json --markers markers.json --bottom-z <ft> --top-z <ft> --depth <ft> --padding 1 --tolerance-ft 1.0 --level-z <plan level elevation> --out plan.json
   ```

   A mark closer than the tolerance to an existing marker (and within 10 degrees of parallel) is a duplicate. So is a mark that repeats an earlier mark. Duplicates get no box. Show each one to the user with the existing marker and the distance. Exit code 1 means duplicates were found.
5. **Ask** (AskUserQuestion, one decision per question): the detail view type and template (count the templates of existing Detail views and offer the top 3), and where the markers show:
   - **Markers on the finish floor plans only (Recommended)**: see step 9.
   - **Markers in every view that cuts them**: the Revit default.
6. **Preview** one row for each new view: name, look direction as a compass direction, cut line, template, sheet.
7. **Apply** (one transaction, dry run first). For each planned box, build a `BoundingBoxXYZ` from `plan.json` (`box.origin`, `basis_x`, `basis_y`, `basis_z`, `min`, `max`; the frame is right-handed, as `BoundingBoxXYZ` requires) and call `ViewSection.CreateDetail(doc, detail_type_id, box)`. Then check the direction at once: `ViewDirection` must be minus the planned look (`section_marks.view_direction_ok`). If not, stop. Do not flip it in a second run. Set the name and the template.
8. **Hide grids, levels and other markers in each new detail view.** Level heads, grid bubbles and the markers of other views made the viewports larger than their crop. Hide the categories Grids, Levels, Sections, Elevations and Callouts in each new view (`View.SetCategoryHidden`). When the view template controls Visibility/Graphics, the view cannot change it. Then propose a template that hides them, and say which views use that template.
9. **Markers on the finish floor plans only.** A detail section shows its marker in every view that cuts it. It has no "Show in" setting. What worked:
   - On each new section, set "Hide at scales coarser than" (`SECTION_COARSER_SCALE_PULLDOWN_IMPERIAL`, or `..._METRIC`) to 12" = 1'-0". Read the parameter first and keep its storage type. Check the value in the dry run.
   - On each finish floor plan, add a view-specific reference section at the same spot: `ViewSection.CreateReferenceSection(doc, plan_id, new_view_id, head, tail)`. Use the ends of the cut line. Check the head and tail against the look direction.
   - To move a cut later: set the scale back, move the section, then set the scale again. Tell the user this in the summary.
   - A view filter is another way. It must be on the Sections category with the rule "Sheet Number does not equal <sheet>". A rule on the markers' own category fails with "One of the given rules refers to a parameter that does not apply to this filter's categories", because that category offers only Workset. A template change reaches every plan that uses the template. Say how many before you apply.
10. **Use the target view id.** In every later query, find the plan or the new view by its id (or name). Do not use `doc.ActiveView`. After a view change, `doc.ActiveView` can be the sheet, and a query then finds nothing, with no error.
11. **Verify.** Re-read each new view's `ViewDirection` and compare it with the planned look. Then do step 8 of the skill. Capture a sheet by its name, not its number.

## Keynote tags

Revit cannot place a material keynote tag on a cut floor layer. `IndependentTag.Create` with a face reference fails with "The reference can not be tagged". An element reference creates the tag, but `TagText` reads empty for every keynote and material tag type tried. The `TM_ADDBY_MATERIAL` mode creates a Material Tags tag that also reads empty. The workaround from the field report is a text note that carries the keynote value from the floor type's `Keynote` parameter. Use text notes when the user asks for keynotes on these details. The full note is in `am-revit-api-docs`.

## Tests

`python -m pytest "<skill dir>\tests" -q`, or `python "<skill dir>\tests\test_detail_views.py"` without pytest.

# Recipe: annotate a detail view, with a drawing preview

Example request: "Finish the empty transition detail on A501 like the other details on that sheet."

This recipe draws 2D annotation in a detail view that has only the model cut: filled regions (for example finish layers and a metal strip), detail lines (for example screw and anchor holes) and text notes with leaders. It copies the house style from finished details. It comes from issue #298. To make the cut and its marker, use [detail-views.md](detail-views.md) first.

The user reviews a drawing, not only a table. In the field session the user asked for this after the table preview: "i want to review the drawing in html". The drawing preview is the planned geometry as SVG over a capture of the view.

Files (paths relative to the am-safe-change skill folder):

| Step | File | Where it runs |
|---|---|---|
| 3 Read | `scripts/read_detail_annotation.py` | Revit, `run_query` |
| 3 Style | `scripts/detail_annotation_preview.py style` | Terminal |
| 4 Compute | `scripts/detail_annotation_preview.py compute` (uses `scripts/lib/detail_annotation.py`) | Terminal |
| 5 Drawing preview | `scripts/detail_annotation_preview.py draw` | Terminal, after `capture_view` |
| 7 Execute | `scripts/apply_detail_annotation.py` | Revit, `run_modify` (dry run, then real) |
| 7 Side effects | `scripts/detail_annotation_preview.py side-effects` | Terminal |
| 7, 8 Compare | `scripts/detail_annotation_preview.py compare` | Terminal |

View coordinates: every point in this recipe is (u, v) in feet. u goes to the right and v goes up, in the view plane, from `View.Origin` along `View.RightDirection` and `View.UpDirection`. The scripts change them to model points. So every new element lies in the view plane.

## Step 2: questions to ask

Ask only what the request leaves open. Use AskUserQuestion, one decision per question:

1. **Which view?** The empty detail view. Name it back with its sheet and detail number.
2. **Which details show the house style?** The finished details on the same sheet (Recommended), or a sheet the user names. The style step proposes the closest one.
3. **What goes in the detail?** The finish layers, the transition strip, the fixings and the notes. Copy linework from the closest reference when it shows the same part (Recommended).
4. **Where do the finish layers go?** Ask this only when the geometry check in step 3 finds a problem, for example finish floors under a raised slab. Show the measured heights. Do not guess.

## Step 3: read the style and the model cut

1. Run `scripts/read_detail_annotation.py` with `run_query`. Use `inputs: {"view_id": <target>, "sheet_ids": [<sheet>]}`, or list the reference views in `reference_view_ids`. Save the result as `read.json`. It has, for each view, the view frame, the crop region, and every filled region, detail line and text note (type, points, leader layout). It also lists the filled region types, line styles and text note types of the model.
2. Sum up the style:
   `python "<skill dir>\scripts\detail_annotation_preview.py" style --read read.json --view <target>`
   It lists the types, line styles and leader layouts of each reference view, and names the closest finished detail (the most items, with at least one filled region and one text note). The field session read 28 views by hand to find this.
3. Check the model cut before you draw. Find the top of each finish and the joint position with a ray test. What worked in the field:
   - `ReferenceIntersector` on an existing 3D view returned no hits.
   - A temporary isometric 3D view, made inside the `run_query` (the query rolls back), with `FindReferencesInRevitLinks = True`, worked. It took about 18 s for 8 rays.
   - Cast vertical rays down at points on both sides of the joint. Report the hit elevations of the finish floors and the slab.
   - If a finish floor sits under a raised slab, or the heights do not match the reference, stop and ask question 4.

## Step 4: compute

Write a plan file `plan.json` in view coordinates. Use the crop region and the read points of the reference detail.

```json
{"view_id": 100, "title": "Annotate transition detail",
 "copy": [{"from_view_id": 200, "ids": [302, 303], "offset": [0.5, 0.0]}],
 "items": [
  {"kind": "filled_region", "type": "<filled region type>", "loops": [[[0, 0], [1, 0], [1, 0.03], [0, 0.03]]]},
  {"kind": "detail_line", "style": "<line style>", "start": [0.5, 0], "end": [0.5, -0.1]},
  {"kind": "text_note", "type": "<text note type>", "text": "FINISH B", "at": [0.5, 0.6], "leader_end": [0.5, 0.02]}]}
```

- `copy` translates filled regions and detail lines of a reference view by `offset` (u, v). Leave `ids` empty to copy all of them. Text notes are never copied: the new detail needs its own text.
- A text note is centered (`"align": "Center"`) with the leader on the top line (`"leader_left": "TopLine"`) by default. Put `leader_end` straight below `at`. See "Centered note with a vertical leader" below.

```powershell
python "<skill dir>\scripts\detail_annotation_preview.py" compute --read read.json --plan plan.json --out preview.json
```

The command prints the chat table. Exit code 1 means BLOCKED. Blocking warnings: a type or line style name that is not in the model (or is used twice), a loop with fewer than 3 points, a zero-length line, a note with no text, and a point outside the crop region (the element would not show). Then do the ownership check of the skill (step 4). The preview lists the view id in `ownership_ids`.

## Step 5: preview as a drawing, then as a table

1. Capture the view with `capture_view`. Save the PNG.
2. Pick two points that show in the capture and that you know in view coordinates, for example two corners of a reference filled region. Read their pixel positions in the capture. The two points must differ in both u and v.
3. Draw:

   ```powershell
   python "<skill dir>\scripts\detail_annotation_preview.py" draw --preview preview.json --capture view.png --known "-1,0:212,388" --known "0,0.1:340,375" --out preview-drawing.html
   ```

   Open the page in the Browser pane. It shows the planned items over the capture (filled regions orange, detail lines red, notes and leaders blue), then the notes, the warnings and the table.
   - The command warns when the two points give different x and y scales. Then check the points.
   - Without `--known`, the crop region fills the image. This is correct only when the capture shows exactly the crop region. A panned or zoomed view moves the overlay.
   - Without `--capture`, the page draws the plan on a blank sheet with the crop region.
4. Also render `preview.json` with the schedule viewer (skill step 5) and print the chat table.

## Step 7: execute

1. `run_modify` with `dry_run: true`, the content of `scripts/apply_detail_annotation.py`, and `inputs: {"preview_path": "<full path to preview.json>"}`. Save the result as `dryrun.json`.
2. Compare: `python "<skill dir>\scripts\detail_annotation_preview.py" compare --preview preview.json --actual dryrun.json`. It must print `MATCHES PREVIEW`.
3. Side effects: `python "<skill dir>\scripts\detail_annotation_preview.py" side-effects --preview preview.json --dryrun dryrun.json`.
   - Each new filled region adds its own sketch. In the field, 3 filled regions added 38 elements: 18 `<Sketch>` lines, 14 "Automatic Sketch Dimensions" and 6 with no category (the sketch and its sketch plane). The real run gave the same counts.
   - The preview lists these categories in `expected_dependent_categories`, so the side-effects command and `dry_run_checks.py change-list` do not flag them. Tell the user the count in one sentence. Any other category is still a stop.
4. Do the content checks and the change-list review of the skill (step 7). The new text notes are annotation: name each one with its text (before: none, after: the planned text).
5. `run_modify` with the same script and inputs, without dry run. The user clicks Keep or Discard in Revit.

The apply script first checks that the view still has the preview's origin and directions, and that every type and line style still exists. Then it creates all items in one transaction and re-reads them by id.

## Step 8: verify

Compare the real run result with the preview (the same `compare` command). Then capture the view again and show it next to the drawing preview. Do the plan graphics check in [plan-graphics.md](plan-graphics.md). Then do step 8 of the skill.

## Centered note with a vertical leader

This layout matched the finished details at the first try:

```python
options = DB.TextNoteOptions(text_type_id)
options.HorizontalAlignment = DB.HorizontalTextAlignment.Center
note = DB.TextNote.Create(doc, view.Id, point, text, options)
note.LeaderLeftAttachment = DB.LeaderAtachement.TopLine   # Revit spells it "Atachement"
leader = note.AddLeader(DB.TextNoteLeaderTypes.TNLT_STRAIGHT_L)
leader.End = end_point   # straight below the note; set only End
```

Revit puts the anchor and the elbow at the bottom center of the note, so the leader is vertical.

## Not verified

- The scripts are tested with stand-ins, not in Revit. The field session used its own scripts with the same API calls.
- Seen on one detail view type in Revit 2026 only.
- `capture_view` mode `export` could give an exact pixel mapping. In one model it returned `internal_error`, so this recipe uses two known points.

## Tests

`python -m pytest "<skill dir>\tests\test_detail_annotation.py" -q`

# Focus a view on the current Revit selection

Use am-safe-change. Select one to 100 host model elements. Choose a new 3D view, an existing orthographic 3D view, or a rectangular plan crop. Save or sync before reading the model.

1. Call `get_context` and `get_skill("revit-scripting")`. Run `scripts/focus_view.py` with the scripts directory as `workspace` and `mode: "read"`. Use a request such as `{"action":"create_3d","target_id":"12","name":"Focused review","padding_ft":1}`. The target is a 3D view type for creation. Use `reuse_3d` or `crop_plan` with an existing view ID and omit the name.
2. If a target is on a sheet, review the sheet and viewport IDs. Model and annotation clipping can affect the sheet. Add `"allow_placed":true` only for the reviewed scope. Use a supported view without a template, scope box, split, or linked dependent views.
3. Recover the full query result with `get_run` if needed. Save it as `read.json`. Run `python focus_view_preview.py compute read.json preview.json` from the scripts directory.
4. Check ownership for an existing view. A new view has zero existing write targets. Show the preview, review the padding and proposed extents, and obtain approval. The preview lists the selected IDs and any sheet placement in its basis.
5. Run `focus_view.py` with `run_modify` and `dry_run:true`. Use `{"mode":"apply","plan":<preview.json contents>}`. Save the full dry-run envelope. Run `python focus_view_preview.py side-effects preview.json dryrun.json`. Stop if the outcome, IDs or telemetry differ from the preview.
6. Repeat the read query. Run `python focus_view_preview.py baseline preview.json fresh-read.json`. Stop if the name, view, geometry, selection, active view, or ownership changed. A new view must still be absent after the dry run.
7. Run the same approved plan under the current policy. Use Keep or Discard in Revit. Under auto policy, get the second approval after the dry run.
8. After Keep, run a fresh query before opening the view. Use `{"mode":"verify","action":"create_3d","view_id":"<kept ID>","view_uid":"<kept UID>"}`. Use the actual action and IDs from the kept result. Run `python focus_view_preview.py compare preview.json kept-read.json`. Read ownership for the created or edited view if the model is workshared. After Discard, repeat the original read and check that its state matches.

Open the verified view in Revit when needed. Check that the selected elements are visible. The box can contain elements that the view hides by phase, range, category, or other settings.

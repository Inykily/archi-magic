# Recipe: material colors (with a live panel)

Example request: "Let me pick the colors for the floor materials by eye, then write them to Revit."

Files (paths relative to the am-safe-change skill folder):

| Step | File | Where it runs |
|---|---|---|
| 3 Read | `scripts/read_materials.py` | Revit, `run_query` |
| 4 Panel | `scripts/render-panel.ps1` + `assets/material-colors-panel.html` | Terminal, PowerShell |
| 4 Compute | `scripts/material_preview.py compute` (uses `scripts/lib/material_colors.py`) | Terminal, CPython 3 |
| 4 Palette | `scripts/material_preview.py palette` | Terminal, CPython 3 |
| 7 Execute | `scripts/apply_material_colors.py` | Revit, `run_modify` (dry run, then real) |
| 7 Side effects | `scripts/material_preview.py side-effects` (uses `scripts/lib/side_effects.py`) | Terminal, CPython 3 |
| 7, 8 Compare | `scripts/material_preview.py compare` | Terminal, CPython 3 |

## Step 2: questions to ask

Ask only the questions that the request leaves open. Use AskUserQuestion, one decision per question:

1. **Which materials?**
   - One material group the user names, for example "all floor materials" (Recommended): the panel shows only that group.
   - Every material in the model: the panel shows all of them.
   - A custom list: the user names the materials.
2. **What changes?**
   - Shading color only (Recommended): the color Revit shows in shaded views.
   - Shading and surface pattern color: the fill pattern color changes too.
   - Surface pattern color only.

Then say the scope back in one sentence, for example: "I will let you tune the shading colors of the 10 floor materials in a panel, then preview, dry run and apply them."

## Step 3: read

`run_query` with the content of `scripts/read_materials.py`. Save the JSON result as `read.json`. The result has every material: `id`, `name`, `shading` (RGB or null), `surface_pattern_id`, `surface_pattern_name`, `surface_pattern_color` (RGB or null), and `used_by_categories` (the categories of elements that use the material). The used-by scan stops at 20,000 elements; `used_by_truncated` is true when it stopped early.

## Step 4: panel, then compute

1. Render the panel from the read result:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "<skill dir>\scripts\render-panel.ps1" -Json <read.json> -Out <panel.html>
   ```
2. Open `panel.html` in the Browser pane (`preview_start` with the `file:///...` URL). If no Browser pane is available, give the user the path. The panel needs no server. The page cannot talk to Revit.
3. In the panel the user tunes colors by eye: a color picker plus RGB boxes per row, a swatch preview, reset per row and for all, and a count of changed rows.
4. **Palette helper.** The panel has a "Suggest greys" box: pick a material, ask for N light greys, click one to use it as that material's shading. Each grey states its WCAG contrast ratio against black text and against the material's pattern color. The greys run from white down to the darkest grey that still keeps black text at 4.5:1 (WCAG AA for normal text). The same helper runs in chat:
   ```powershell
   python "<skill dir>\scripts\material_preview.py" palette --count 5 --foreground 90,90,90
   ```
   `--foreground` is the pattern foreground RGB the greys must show (default black). The panel and the command compute the same greys, up to 1 RGB step of rounding.
5. The user clicks **Copy changes for Revit** in the panel and pastes the JSON back in chat. Save it as `colors.json`. The JSON has kind `material-colors` and only the rows the user changed.
6. Compute the preview:
   ```powershell
   python "<skill dir>\scripts\material_preview.py" compute --request colors.json --read read.json --out preview.json
   ```
   The command prints the chat table. A warning of type `low_pattern_contrast` (not blocking) means a pattern color is hard to see on the new shading (contrast below 3:1). The preview's `expected_dependent_categories` are the categories that use the changed materials, plus Keynote Tags and Legends, which redraw when a material changes (issue #28).

The panel never writes to Revit. It only produces the request JSON. The change still goes through steps 5 to 8 of the skill.

## Step 7: execute

1. `run_modify` with `dry_run: true`, the content of `scripts/apply_material_colors.py`, and `inputs: {"preview_path": "<full path to preview.json>"}`. Save the result as `dryrun.json`.
2. Compare:
   `python "<skill dir>\scripts\material_preview.py" compare --preview preview.json --actual dryrun.json`
   It must print `MATCHES PREVIEW`. If it prints `DIFFERENT`, stop.
3. Show the side-effect counts:
   `python "<skill dir>\scripts\material_preview.py" side-effects --preview preview.json --dryrun dryrun.json`
   Show the two numbers in chat: elements the script edited on purpose, and dependent elements Revit regenerated. Say in one sentence why dependents change (the command prints it). If the command warns about an unexpected category (for example Walls when the change targets floor materials), tell the user and ask whether to continue before you apply.
4. `run_modify` with the same script and inputs, without dry run. The user clicks Keep or Discard in Revit.

The apply script first checks that every material still has its "before" colors. Then, in one transaction, it sets each material's Color and, when the step has one, its Surface Foreground Pattern color. It returns the colors of each material after the change.

A material change also changes elements that use the material (floors, tags, legend parts). So the change set in Revit lists more elements than the number of materials. In the issue #28 example, a change to 10 materials reported `modified_count: 1143` (292 floors, 831 keynote tags, legend components).

## Step 8: verify

Run `read_materials.py` again, save it as `verify.json`, then:
`python "<skill dir>\scripts\material_preview.py" compare --preview preview.json --actual verify.json`

## Tests

`python -m pytest "<skill dir>\tests" -q`, or `python "<skill dir>\tests\test_material_colors.py"` without pytest.

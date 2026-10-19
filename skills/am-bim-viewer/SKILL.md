---
name: am-bim-viewer
description: Show a Revit model in 3D inside Claude Code. Export visible elements of the active Revit view to JSON with the pyRevit Agent Runtime, build a self-contained interactive viewer page (Rhino-style camera, click an element to see its category, family, type, level, id and parameters, category filters, named views), and open it in the app's Browser pane. Triggers on "show the model in 3D", "3D viewer", "view this Revit model", "bim viewer", "/bim-view", "export geometry to JSON", "orbit the model like Rhino".
---

# am-bim-viewer

Show Revit geometry as an interactive 3D page next to the conversation.

## What it is

- **The mod** (`mods/am-bim-viewer`, a separate plugin in this marketplace) adds the `/bim-view` command. It builds the viewer page from a JSON file, writes it next to that file, and opens a **BIM view pane** in the session.
  - The pane draws the model as a static picture (SVG) with buttons for the named views, rotate and zoom steps, category toggles, an element list and the element data. Hover an element to see its name and ID.
  - A mod pane cannot run WebGL or page scripts (the desktop `Svg` element is script-less). So the full interactive viewer is an HTML page. The mod opens it in the Browser pane when the engine has the Claude_Browser server; otherwise Claude opens it.
- **This skill** holds the Revit exporter, the demo generator, a node build script and the tests.

## Steps

1. **Export from Revit.** Check that Revit runs with the agent host: `& "$env:APPDATA\pyRevit-Master\bin\pyrevit.exe" agent status`. Then run the exporter in query mode (read-only):
   ```
   & "$env:APPDATA\pyRevit-Master\bin\pyrevit.exe" agent run "<this skill dir>\scripts\export_bim_json.py" --mode=query --revit=2026
   ```
   With `SOURCE = "auto"` it exports the active view when that is a 3D view, else the whole model. Set `CATEGORIES` and `LEVEL` to export a subset. It prints one JSON line with the file path (default `%TEMP%\am-bim-viewer\<model>.json`), the element and triangle counts, and what it skipped. Tell the user about each skip count that is not zero. Change the caps with `MAX_ELEMENTS` and `MAX_TRIANGLES` at the top of the script. Tested live on Revit 2026.3 (Snowdon Towers sample: 1595 elements, 110,015 triangles, 5.7 MB JSON, about 2.5 minutes, no model change).
2. **Build the page.** Use `/bim-view <path.json>` (the mod), or with node: `node "<this skill dir>\scripts\build-viewer.mjs" <path.json>`. With no path, both build the demo model. The mod cannot read files over 4 MiB (about 80,000 triangles). Use the node script for larger models.
3. **Open it.** Open the `file:///...viewer.html` URL in the Browser pane (`preview_start` with `url`). If no Browser pane is available, give the user the path, or run `/bim-view <path> --open` to use the default browser.

## Viewer controls (Rhino defaults)

| Action | Perspective view | Top / Front / Right (parallel) |
|---|---|---|
| Right drag | Rotate (turntable around world Z) | Pan |
| Shift + right drag | Pan | Pan |
| Ctrl + right drag up/down | Zoom (up = in) | Zoom |
| Ctrl + Shift + right drag | Rotate | Rotate (stays parallel) |
| Wheel | Zoom at the cursor | Zoom at the cursor |
| Ctrl + wheel | Zoom at the view center | Zoom at the view center |
| Left click | Select. The side panel shows the data. Click empty space to clear | Select |
| Double-click | Zoom to the element (target = its center). On empty space: zoom extents | Same |
| Middle drag | Pan (extra, not a Rhino default) | Pan |

Sources: https://www.rhino3d.com/docs/guides/modeling/rhino-windows-navigation/, https://docs.mcneel.com/rhino/8/help/en-us/seealso/sak_navigate.htm, https://docs.mcneel.com/rhino/8/help/en-us/commands/zoom.htm. The rotate direction is not in the docs: the near face of the model follows the cursor.

## Orientation

- Revit and Rhino use the same frame: right-handed, X = East, Y = North, Z = Up. The JSON keeps Revit internal coordinates in decimal feet.
- "North" here is **Project North** (Revit internal Y). The exporter does not apply the True North rotation. (The Snowdon sample has True North at 26 degrees.)
- The ground grid lies in the XY plane at the base of the visible model. It fades out at about 1.75 times the model size.
- The viewer does not rotate or mirror the data. It builds the camera from azimuth and elevation around world Z (`mods/am-bim-viewer/viewer/viewer-core.mjs`).
- Top: looks down -Z, North at the top, East to the right. Front: looks from -Y toward +Y. Right: looks from +X toward -X. Perspective: from the south-east, above.
- The axis gizmo shows X red, Y green, Z blue.

## JSON schema (`am-bim-viewer/1`)

```json
{
  "schema": "am-bim-viewer/1", "units": "ft",
  "source": { "title": "Model name", "view": "3D View" },
  "elements": [{
    "id": 310000, "category": "Walls", "name": "Basic Wall", "family": "Basic Wall", "type": "Generic - 9\"",
    "level": "Level 1",
    "params": { "Unconnected Height": { "v": 12, "u": "ft" }, "Mark": "W-S" },
    "mesh": { "vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0], "indices": [0, 1, 2] }
  }],
  "annotations": [{ "text": "N (+Y)", "position": [-10, 12, 0] }]
}
```

`vertices` is a flat list of x, y, z in feet. `indices` holds three vertex indices for each triangle. A parameter with a unit is `{ "v": number, "u": "ft" | "sq ft" | "cu ft" }`. The panel shows it in feet and metres.

## Tests

From this skill's folder: `npm install`, then `npm test` (orientation, camera mapping, click and double-click, ground grid, inline SVG; on the real three.js 0.160.0 cameras), then `npm run mutate` (breaks the code in 16 known ways; every break must make a test fail). In the browser, run `tests/browser-check.js` in the built demo page. The mod has its own tests: `claude plugin test mods/am-bim-viewer`.

## House rules (all am-* skills)

- Write all output to the user in ASD-STE100 Simplified Technical English. Use short sentences (max 20 words for instructions, 25 for descriptions). Use active voice. Put one instruction in each sentence, and start it with the verb. Use one word for one meaning. Explain any technical term the first time you use it, because many users are architects, not programmers.
- When a task has independent parts (for example, several files to check or several Revit years to compare), do them in parallel with subagents. Keep steps that depend on each other in sequence.

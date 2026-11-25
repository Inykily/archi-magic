# Recipe: match the live model to an existing axon drawing (issue #272, first step)

Use this recipe when the user wants the live 3D model to replace a static axonometric picture (for example a site-plan slide), with the same camera and the same look.

Status: the camera fit is a script with tests (`scripts/axon_fit.py`). The viewer page does not yet have a locked axon mode, an image overlay or a per-view style sheet. Build those in the custom page, with the checks below.

## 1. Ask for the sources first

- Ask which file is the source for each part of the drawing (the project model, a context model, a separate expansion file). Do not model stand-in boxes before you ask.
- Ask for the reference image at full size. Record its width and height in pixels.

## 2. Fit the camera

1. Pick four or more landmarks that show clearly in the image and in the model (building corners, a property-line corner, a road edge). Do not pick them all on one line. Spread them over the image.
2. For each landmark, write the model point (x, y, z in feet, the export units) and the image point (pixels, x to the right, y down):
   ```json
   {"image": {"width": 1600, "height": 1000},
    "pairs": [{"name": "NE corner", "model": [120, 80, 0], "image": [1180, 402]}]}
   ```
3. Run `python "<this skill dir>\scripts\axon_fit.py" landmarks.json --out camera.json`.
4. Read `residuals`. Each value is the error of one landmark in pixels. If one landmark has a much larger error than the others, it is probably picked in the wrong place. Fix or remove it, and run the fit again.
5. Use `azimuth`, `elevation` (radians, the viewer convention), `target`, `viewHeight` and `viewWidth` for a three.js `OrthographicCamera`. Lock the camera: turn off orbit, pan and zoom in this view.

The fit has five unknowns: azimuth, elevation, scale and a 2D offset. A general 8-unknown fit can be degenerate with four landmarks, so do not use it. The fit assumes a true parallel projection. It does not fit a perspective rendering.

## 3. Prove the fit

- Show the reference image at 50% opacity over the live view. Check the property line and two buildings against it.
- Report the largest landmark error (`maxPx`) to the user.

## 4. Match the graphics

- Keep one style sheet for each view: layer colors, outline on or off, one highlight for the project site, line width and dash.
- Draw site lines and arrows as wide lines (three.js `Line2`) with the depth test on, so a line never shows through a building. Use "draw on top" only for labels.
- Mark generated objects (outlines, helpers) and skip them when you add outlines. Otherwise each pass outlines the outlines of the last pass.
- Fit the shadow camera to the ground that the camera sees. Use a 4096 shadow map and a normal bias for sharp shadows over a large site.
- For a legend-to-layer highlight, store the original state of each material before the fade. Then the reset is exact. Ghost the other layers.

## 5. Test in a hidden Browser pane

- `requestAnimationFrame` stops while the pane is hidden. So add a debug hook that steps each fade to its end, and use it in the checks.
- Disable CSS transitions before a screenshot (see "3D-anchored labels" in `SKILL.md`).

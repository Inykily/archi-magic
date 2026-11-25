# Recipe: public embed page for a whiteboard (issue #288, first step)

Use this recipe when the user wants one model in a whiteboard frame (for example Miro), with no sign-in.

Status: the URL settings and the link checks are a script with tests (`scripts/embed_settings.py`). The viewer page in this skill does not yet have display modes, quick views, idle spin or the option morph. Build those in the custom embed page, with the pitfalls below.

## 1. Agree what is public

- An embed link opens with no sign-in. Anyone with the link sees the model. Ask the user to confirm that the project allows this. Model data is project data.
- Publish only an export made for the embed (geometry and option names). Leave out parameters, element ids and names that the frame does not need.

## 2. Use the URL settings

Each whiteboard frame keeps only its link. So the page reads its state from the URL:

| Setting | Values | Default |
|---|---|---|
| `option` | design option number, 1 to 99 | 1 |
| `bar` | 0 hides the option switch | 1 |
| `view` | `3d`, `plan` (site plan), `n`, `e`, `s`, `w` (elevations) | `3d` |
| `display` | `clay`, `shaded`, `pen` | `clay` |
| `spin` | 0 stops the idle spin | 1 |

- Read a link: `python "<this skill dir>\scripts\embed_settings.py" parse "<link>"`. A bad value falls back to its default with a warning, so the frame always opens.
- Write the shortest link for a state: `python "<this skill dir>\scripts\embed_settings.py" build --option 2 --bar 0 --view e`.
- Use the same rules in the page script. The test file `tests/test_embed_settings.py` is the contract.

## 3. Open the public route safely

- Allow exact files only, one rule for each file. Do not use a prefix rule: an encoded `..%2f` path can reach private pages through it. Check each path with `embed_settings.py check-path <path> --allow <file>`.
- Send `Referrer-Policy: no-referrer` and `X-Robots-Tag: noindex` on every embed response. `missing_headers()` in the script names any that are missing.
- Use a long random file name for each model. To revoke a link, remove its file and its allowlist rule. Then check that the old link fails.
- Check the deployed version, not the merged code. Open the link in a private window with no session, and inside the whiteboard. A merge does not prove a deploy.

## 4. three.js pitfalls (each cost one debug round)

- A `LineMaterial` (wide lines) made after the last `resize()` keeps a 1 x 1 resolution and draws huge arcs. Give each new line material the current canvas size.
- `EffectComposer` (needed for ambient occlusion) drops the anti-aliasing of the renderer. Pass a multisampled `WebGLRenderTarget` (`samples: 4`).
- A style pass that changes `material.color` in place also changes cached display-mode materials. Apply the display mode again after each style pass.
- A switch between parallel and perspective draws one wrong frame. Set up the target camera fully before the switch.
- A white `MeshBasicMaterial` turns gray under ACES tone mapping. Use `toneMapped: false` in the line-drawing modes.
- In a hidden Browser pane, animation frames stop and screenshots lag one step. Drive frames by hand in tests. Read the active camera again on each frame, because a stored reference goes stale when the camera type changes.

## 5. Acceptance checks

- The link opens in a private window and inside the whiteboard with no sign-in.
- `?option=2&bar=0&view=e&display=clay` opens on that state.
- An option switch does not move the camera. A quick-view flight turns a few degrees per frame at most.
- Edges stay smooth in the modes with ambient occlusion.

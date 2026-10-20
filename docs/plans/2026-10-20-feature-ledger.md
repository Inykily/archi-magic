# archi-magic: feature request ledger (session 2026-10-19 to 10-20)

Every feature the user asked for in the build session, with its status. **Shipped** means merged to `main` on GitHub. Since PR #4, every merge is a new plugin version (commit-derived) with a dated release tag.

| # | Request (user's words, condensed) | Delivered as | Status |
|---|---|---|---|
| 1 | Update pyRevit 6.4 to 7.0 without admin rights; Revit kept loading 6.4 | Per-user manifest repoint; `am-pyrevit7-setup` | Shipped (v0.1.0) |
| 2 | One guide to forward to the team, so their Claude handles everything | `kit-README.md`; `Setup-pyRevit7.cmd`; the skill | Shipped |
| 3 | Streamline the pyRevit 7 install inside that guide | `-Install` step (silent install, signature check) | Shipped |
| 4 | Agent Runtime pointing, so Claude Code can talk to Revit right away | `-EnableAgent` (agent host + MCP registration) | Shipped |
| 5 | Note that a model must be open (an Autodesk sample is fine) to verify | Skill and kit text | Shipped |
| 6 | A package (script + guide) to drop on other users' machines | `pyrevit7-agent-runtime-kit` zip | Done (local zip) |
| 7 | A public plugin repo `archi-magic`, all skills prefixed `am-*` | github.com/zsenarchitect/archi-magic | Shipped |
| 8 | Skill: read the pyRevit documentation | `am-pyrevit-docs` | Shipped (v0.3.1) |
| 9 | Skill: read the Revit API documentation | `am-revit-api-docs` | Shipped (v0.3.1) |
| 10 | Intro skill for architects who have never used developer tools | `am-welcome` | Shipped (v0.3.1) |
| 11 | The intro must not go stale; a reminder to update it every week | Live skill list + CI drift check (shipped); **weekly GitHub reminder** | Partial: add the weekly reminder workflow |
| 12 | Plugin preference: ASD-STE100 output; subagents for parallel tasks | `HOUSE-RULES.md` (shipped); SessionStart rules hook | Rules shipped; hook in P0 work |
| 13 | Ask questions with clickable options when something is unclear | House rule | Shipped (v0.3.1) |
| 14 | Preinstall popular skills: superpowers (plan, debug ...) | Pinned dependency | Shipped (v0.3.1) |
| 15 | grill-me as a dependency skill | `am-grill-me` + `am-grilling` (MIT copy) | Shipped (v0.3.1) |
| 16 | frontend-design as a dependency | Pinned dependency | Shipped (v0.3.1) |
| 17 | A version system and bump process, so user copies don't go stale | `bump-version.ps1`; CI version guard; README auto-update note | Shipped; the guard gets inverted in P0 work |
| 18 | Mod: 3D view in Claude Code, interactive, BIM side info, Rhino camera, correct orientation | `am-bim-viewer` skill + mod | Shipped (v0.4.1, PR #2) |
| 19 | Viewer: prettier, using naturalUIUX/frontend-design, no plain checkboxes, better fonts and palette | frontend-design restyle (naturalUIUX skill not found on this machine) | Shipped (v0.4.1, PR #2) |
| 20 | Viewer: inline display inside the Claude Code session | In-session pane (picture + controls) plus the full 3D page in the Browser pane; panes cannot run WebGL | v0.4.0 (platform limit documented) |
| 21 | Viewer: select-element highlighting the whole viewport | Was the browser's element picker; in-viewer click selects one element (tested) | Shipped (v0.4.1, PR #2) |
| 22 | Viewer: double-click to zoom to the selected element | Done, with tests | Shipped (v0.4.1, PR #2) |
| 23 | Viewer: move the demo door along the south wall | Done | Shipped (v0.4.1, PR #2) |
| 24 | Viewer: grid fixed to the screen; attach it to the model base and feather it out | World-space ground grid with radial fade | Shipped (v0.4.1, PR #2) |
| 25 | Viewer: cute, round-cornered, fat cursor | Five SVG cursors (`9929add`) | Shipped (v0.4.1, PR #2) |
| 26 | Local log writer for self-debugging and self-healing | `scripts/lib/am-log.ps1` + `am-doctor` | Shipped (v0.4.1, PR #2) |
| 27 | Have 4 agents review the design and propose enhancements | Review triage plan; P0 fixes | P0 fixes in progress |
| 28 | Research Utopia5327/revit-bim + Autodesk Revit MCP for ports | `am-model-health`, `am-param-qa`, `am-workset-audit`, `am-area-report` | Shipped (v0.4.1, PR #2) |
| 29 | Rhino connection through RhinoCode and ScriptServer | `am-rhino-setup` on McNeel's official `rhino-mcp`; **RhinoCode CLI / StartScriptServer fallback missing from the docs** | v0.4.0, fallback to add |
| 30 | Official Rhino MCP: depend on it, don't reinvent it | `rhino-mcp` listed in the marketplace, pinned, on demand | Shipped (v0.4.1, PR #2) |
| 31 | Revit doctor: diagnose crashes; find the latest journal and analyze it | `am-revit-crash-doctor` | Shipped (v0.4.1, PR #2) |
| 32 | Revit health: many metrics + an interactive output page | `am-model-health` dashboard mode | Shipped (v0.4.1, PR #2) |
| 33 | Mod to show Revit schedules | `am-schedule-view` skill + mod | Shipped (v0.4.1, PR #2) |
| 34 | Real scenario: shift sheets A301 and up by one; preview before/after before executing | `am-safe-change` (sheet renumber recipe) + preview renderer | Shipped (v0.4.1, PR #2) |
| 35 | Skill: intake many markups (JPG, PDF ...) and conclude what to do | `am-markup-intake` (tested on synthetic markups + live Snowdon mapping) | Shipped (v0.4.1, PR #2) |
| 36 | A very agent-friendly README, because users are not developers | README rewrite | To do |
| 37 | Use the open Revit model for testing | Every Revit skill was tested on Snowdon Towers in read-only or dry-run mode | Done |
| 38 | Sync the repo at good stopping points | v0.3.1 via PR #1; `main` protected | Shipped; v0.4.0 pending |
| 39 | Study the poster reference as the plugin's design system | `design/DESIGN-SYSTEM.md`, `tokens.css`, specimen; contrast measured | Shipped (PR #4, f8cdd7c) |
| 40 | New logos (then: without the 2 stroke lines) | `design/logo/`: tangent-circles mark, night variant, icon tile, small "o." mark; README header | Shipped (PR #4, f8cdd7c) |
| 41 | Auto switch day/night by time of day | `design/theme.js` (07:00-19:00 paper), synced into pages, tested in CI | Shipped (PR #4, f8cdd7c) |
| 42 | Apply the design system to the plugin UIs | dashboard + table page restyled and merged; 3D viewer in progress | Shipped (PR #4, f8cdd7c) |
| 43 | Gumball on the selected element for manual edits | viewer gumball -> pending changes -> "element-transforms" JSON -> `am-safe-change` recipe (preview, dry run, Keep/Discard) | Shipped (PR #4, f8cdd7c) |
| 44 | Merge on main triggers an automatic version bump | commit-derived versions (no pinned version), guard against re-pinning, release tag + notes per merge | Shipped (PR #4, f8cdd7c) |
| 45 | Test with the real Revit model | viewer QA on the live Snowdon export ({3D} view read without changing the active view) | Shipped (PR #4, f8cdd7c) |
| 46 | Night 3D background must be clean, no glare blob / flare | spec rule + viewer fix (flat --bg, no beam/vignette/grain over canvas, test) | Shipped (PR #4, f8cdd7c) |
| 47 | Axis gizmo too large | <=48px, no disc, hairline arms, test | Shipped (PR #4, f8cdd7c) |
| 48 | Cursor rounded and cute; shadow not working | plump rounded cursors; real blur shadow + night halo; pixel-sampling test | Shipped (PR #4, f8cdd7c) |
| 49 | Grid looks like moire texture at distance | fwidth-based minor-line fade, variance test with negative control | Shipped (PR #4, f8cdd7c) |
| 50 | Interaction guide / keybindings in a collapsed panel that expands (animated) on hover over help | viewer help button + animated panel, reduced-motion aware, tests | Shipped (PR #4, f8cdd7c) |
| 51 | First-person walking mode | viewer walk mode: WASD + mouse look, 5.5 ft eye height, floor following, collision, tests | Shipped (PR #4, f8cdd7c) |
| 52 | Help popup too sensitive: open only when hovering the "?" | ? hit area only, 150 ms intent delay, no open during drags, tests | Shipped (PR #4, f8cdd7c) |
| 53 | Gumball supports precise typed input | click-to-type per axis, ft / ft-in / mm / m parser, side-panel numeric fields, tests | Shipped (PR #4, f8cdd7c) |
| 54 | View control must reach Back and other directions: use a view cube | ViewCube (6 faces, edges, corners, compass ring, home) replaces the view buttons and axis gizmo; per-face direction tests | Shipped (PR #4, f8cdd7c) |

## To finish before the v0.4.0 release

1. P0 fixes + SessionStart rules hook (#12, #17, #27). Subagent running.
2. `am-markup-intake` (#35). Subagent running.
3. RhinoCode CLI / StartScriptServer fallback in `am-rhino-setup` (#29).
4. Weekly reminder: a GitHub Action that opens or updates one issue each week. It runs the drift checks and reports upstream pin staleness (superpowers, frontend-design, rhino-mcp, pyRevit latest) (#11).
5. Agent-friendly README (#36).
6. Final checks, version bump, PR, CI green, merge; update the installed plugin on this machine and confirm the skills load.

## Follow-ups (not blocking)

- am-markup-intake: questions such as "Verify door swing" get the next step "Answer the reviewer". A separate "Check in model" step for these may be clearer.
- Found while installing v0.4.1 on the maintainer PC: `claude plugin update` from 0.1.0 did not install the new dependencies (superpowers, frontend-design), so archi-magic failed to load until they were installed by hand. Documented in the README troubleshooting table. Consider an `am-doctor` check for missing dependencies.
- Live checks still to do by hand: the SessionStart rules hook in a new session; the Rhino MCP with Rhino open; the workset fix on a workshared model.

## Not shipped by design (platform limits or open decisions)

- A fully interactive 3D or table view **inside** a session pane. Mod panes cannot run scripts or WebGL, so the interactive versions open in the Browser pane.
- The naturalUIUX skill was not found on this machine; frontend-design was used instead.
- Viewer True North vs Project North, offline vendoring of three.js and fonts, and the large-model size cap are open questions for a later release.

## Verification gaps closed after release (2026-10-20, branch fix/session-gaps)

- Gumball arithmetic input built: `10' - 3"`, `12'6" / 2`, `3 * 2'`, and `90 - 15` for angles. Operators need spaces; without spaces, `10'-3/2"` is still feet-inches. Typing during a drag is now tested (`dragTypingStart`). Result: 61/61 tests, with 3 new mutants killed.
- Help-hover check run against the old behavior: the page built from `c382f3c` (before the hover fix) gave `helpCollapses: false`. The current page gave `true` for all 9 cases (rest, 8 px outside, brief pass, opened, kept over panel, closed after leave, drag ignored, keyboard focus, Esc).
- Walk-mode pointer lock verified in real Microsoft Edge (Playwright, trusted input):
  - A click locks the pointer to the canvas, and the hint changes to "mouse looks around".
  - The control frame with no mouse movement is unchanged. After mouse movement the view changes.
  - Esc exits walk mode.
- Rules hook in a fresh session: this cannot be tested headless here, because the CLI stops at "Not logged in" before SessionStart runs. It needs a signed-in session: a one-click session card is offered.
- Side discovery (not archi-magic): `senzhang-plugin-hub` SessionEnd hooks (`session-end-backup.sh`, `storyline-publish.sh`) fail on this PC. Their bash-syntax commands (`HOME="$(cygpath ...)" bash ...`) run in PowerShell.

## Release status (2026-10-20)

- PR #4 (f8cdd7c) shipped requests 39 to 54. PR #5 (b87681e) fixed the first-release workflow and produced release `r2026.10.20-b87681e30097`.
- Still open, and they need the user or hardware: the rules hook checked in a fresh session, the Rhino MCP checked with Rhino open, the workset move checked on a workshared model, and pointer lock in walk mode (the in-app pane denies it). Filing the pyRevit non-ASCII issue (`docs/upstream/`) needs the user's OK.

# archi-magic: feature request ledger (session 2026-10-19 to 10-20)

Every feature the user asked for in the build session, with its status. **Shipped** means merged to `main` on GitHub. **v0.4.0** means integrated on `release/v0.4.0`, but not merged yet.

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
| 18 | Mod: 3D view in Claude Code, interactive, BIM side info, Rhino camera, correct orientation | `am-bim-viewer` skill + mod | v0.4.0 |
| 19 | Viewer: prettier, using naturalUIUX/frontend-design, no plain checkboxes, better fonts and palette | frontend-design restyle (naturalUIUX skill not found on this machine) | v0.4.0 |
| 20 | Viewer: inline display inside the Claude Code session | In-session pane (picture + controls) plus the full 3D page in the Browser pane; panes cannot run WebGL | v0.4.0 (platform limit documented) |
| 21 | Viewer: select-element highlighting the whole viewport | Was the browser's element picker; in-viewer click selects one element (tested) | v0.4.0 |
| 22 | Viewer: double-click to zoom to the selected element | Done, with tests | v0.4.0 |
| 23 | Viewer: move the demo door along the south wall | Done | v0.4.0 |
| 24 | Viewer: grid fixed to the screen; attach it to the model base and feather it out | World-space ground grid with radial fade | v0.4.0 |
| 25 | Viewer: cute, round-cornered, fat cursor | Five SVG cursors (`9929add`) | v0.4.0 |
| 26 | Local log writer for self-debugging and self-healing | `scripts/lib/am-log.ps1` + `am-doctor` | v0.4.0 |
| 27 | Have 4 agents review the design and propose enhancements | Review triage plan; P0 fixes | P0 fixes in progress |
| 28 | Research Utopia5327/revit-bim + Autodesk Revit MCP for ports | `am-model-health`, `am-param-qa`, `am-workset-audit`, `am-area-report` | v0.4.0 |
| 29 | Rhino connection through RhinoCode and ScriptServer | `am-rhino-setup` on McNeel's official `rhino-mcp`; **RhinoCode CLI / StartScriptServer fallback missing from the docs** | v0.4.0, fallback to add |
| 30 | Official Rhino MCP: depend on it, don't reinvent it | `rhino-mcp` listed in the marketplace, pinned, on demand | v0.4.0 |
| 31 | Revit doctor: diagnose crashes; find the latest journal and analyze it | `am-revit-crash-doctor` | v0.4.0 |
| 32 | Revit health: many metrics + an interactive output page | `am-model-health` dashboard mode | v0.4.0 |
| 33 | Mod to show Revit schedules | `am-schedule-view` skill + mod | v0.4.0 |
| 34 | Real scenario: shift sheets A301 and up by one; preview before/after before executing | `am-safe-change` (sheet renumber recipe) + preview renderer | v0.4.0 |
| 35 | Skill: intake many markups (JPG, PDF ...) and conclude what to do | `am-markup-intake` (tested on synthetic markups + live Snowdon mapping) | v0.4.0 |
| 36 | A very agent-friendly README, because users are not developers | README rewrite | To do |
| 37 | Use the open Revit model for testing | Every Revit skill was tested on Snowdon Towers in read-only or dry-run mode | Done |
| 38 | Sync the repo at good stopping points | v0.3.1 via PR #1; `main` protected | Shipped; v0.4.0 pending |
| 39 | Study the poster reference as the plugin's design system | `design/DESIGN-SYSTEM.md`, `tokens.css`, specimen; contrast measured | design branch |
| 40 | New logos (then: without the 2 stroke lines) | `design/logo/`: tangent-circles mark, night variant, icon tile, small "o." mark; README header | design branch |
| 41 | Auto switch day/night by time of day | `design/theme.js` (07:00-19:00 paper), synced into pages, tested in CI | design branch |
| 42 | Apply the design system to the plugin UIs | dashboard + table page restyled and merged; 3D viewer in progress | partial |
| 43 | Gumball on the selected element for manual edits | viewer gumball -> pending changes -> "element-transforms" JSON -> `am-safe-change` recipe (preview, dry run, Keep/Discard) | in progress |
| 44 | Merge on main triggers an automatic version bump | commit-derived versions (no pinned version), guard against re-pinning, release tag + notes per merge | design branch |
| 45 | Test with the real Revit model | viewer QA on the live Snowdon export ({3D} view read without changing the active view) | in progress |
| 46 | Night 3D background must be clean, no glare blob / flare | spec rule + viewer fix (flat --bg, no beam/vignette/grain over canvas, test) | in progress |
| 47 | Axis gizmo too large | <=48px, no disc, hairline arms, test | in progress |
| 48 | Cursor rounded and cute; shadow not working | plump rounded cursors; real blur shadow + night halo; pixel-sampling test | in progress |
| 49 | Grid looks like moire texture at distance | fwidth-based minor-line fade, variance test with negative control | in progress |
| 50 | Interaction guide / keybindings in a collapsed panel that expands (animated) on hover over help | viewer help button + animated panel, reduced-motion aware, tests | in progress |
| 51 | First-person walking mode | viewer walk mode: WASD + mouse look, 5.5 ft eye height, floor following, collision, tests | in progress |

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

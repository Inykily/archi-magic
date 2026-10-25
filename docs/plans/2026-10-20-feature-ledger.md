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
| 55 | Session start/end hook that prompts users to update to the latest version | SessionStart (startup) hook `hooks/update-check.ps1`: compares the installed commit with the latest release, at most one API call per day, shows a one-line notice with the update steps, opt-out env var, 14 offline tests in CI, 2 mutants killed. SessionEnd not used: its output is not shown in the session. Also fixed the update advice in README and release notes (`/plugin marketplace update` alone does not update the plugin) | Shipped (this PR) |
| 56 | Subagent: make more Rhino skills | `am-rhino-model-health` (read-only check), `am-rhino-area-report` (areas by layer, CSV), `am-rhino-layer-cleanup` (plan, then Apply, one Undo). Self-contained run_python scripts with pure logic tested offline (36 tests, 6 mutants killed); live-tested in a fresh Rhino 8 slot: areas exact (50 + 4 m2), apply trap caught a stale-count bug (fixed), one Undo restored all. Found live: Rhino prints its own lines to stdout, so results use an `AM_RESULT ` line. The first subagent stalled 17 h with no output and was stopped; built in the main thread | Shipped (this PR) |

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
- Live checks still to do by hand: a Rhino tool call with Rhino open; the workset fix on a workshared model. (The rules hook is verified; see below.)

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
- Rules hook in a fresh session: **verified**. A fresh signed-in desktop session (started by the user) reported PRESENT: its context held the `archi-magic rules` block as `SessionStart:startup hook success` before any tool ran. A resumed session showed the same block from the resume hook. Headless CLI runs can still not show it, because they stop at "Not logged in" before SessionStart.
- Side discovery (not archi-magic): `senzhang-plugin-hub` SessionEnd hooks (`session-end-backup.sh`, `storyline-publish.sh`) fail on this PC. Their bash-syntax commands (`HOME="$(cygpath ...)" bash ...`) run in PowerShell.

## Release status (2026-10-20)

- PR #4 (f8cdd7c) shipped requests 39 to 54. PR #5 (b87681e) fixed the first-release workflow and produced release `r2026.10.20-b87681e30097`.
- Pointer lock in walk mode: verified in real Edge (see above).
- pyRevit non-ASCII issue: filed as pyrevitlabs/pyRevit#3812 (open, by zsenarchitect). A search found no duplicate.
- Rhino setup run live on the maintainer PC (no admin):
  - Yak installed Rhino-MCP-Platform 0.3.0 per user. `/plugin install rhino-mcp@archi-magic` installed plugin 0.1.3.
  - `claude mcp list` shows `plugin:rhino-mcp:rhino` as Connected, so the tool names are `mcp__plugin_rhino-mcp_rhino__*` and match the ask rules.
  - A stdio probe (initialize + tools/list, no tool called) returned router 0.3.0 with 32 tools. Two router tools that start or close a Rhino instance, `spawn_slot` and `close_slot`, had no ask rule. They are added now: 28 tools, 56 rules.
  - Fixed: `-Verify` named the `win-arm64` router on an x64 PC. It now picks the router for this CPU.
  - Live tool calls (2026-10-21, user approved starting Rhino): `spawn_slot` started Rhino 8 (slot `aardvark`), `get_context` and `run_python` worked, and the runtime is .NET 8.0.31 (NETCore). `close_slot` closed it.
  - Ask prompt verified 2026-10-22 in Manual (default) mode: the first `spawn_slot` call became a permission request (the app quit before an answer, and no Rhino started). A retry ran only after the user approved the prompt. `close_slot` behaved the same way. Earlier calls in bypass-permissions mode did not prompt, as that mode is designed to do.
  - `SetDotNetRuntime` is covered by the runtime read inside Rhino (.NET 8.0.31 = NETCore).
- Workset move on a workshared model: **verified live 2026-10-21** on a scratch copy of Snowdon in Revit 2026.3. The repo scripts ran unchanged through `exec`.
  - Audit (defaults): 2 worksets, 6 Revit links on Workset1 with no links workset (correctly reported as "no target"), levels and grids already correct, and 14,830 model elements on Workset1.
  - Audit with `links_workset: 189` (a test target): 6 movable moves.
  - `workset_fix.py` dry run: 6 moved, 1 duplicate skipped ("already on ..."), `rolled_back`. A follow-up query confirmed that all links were still on Workset1.
  - Limit found: `EnableWorksharing` fails in the agent runtime ("open transaction phase"). The user turned on worksharing with Collaborate. SKILL.md now says this.
  - Side discovery: `pyrevit run` cannot detect the version of a Revit 2026.3 model (build `1515` is not in its table). Filed 2026-10-22 as pyrevitlabs/pyRevit#3816 (`docs/upstream/2026-10-21-pyrevit-cli-run-build-detection.md`).
  - 2026-10-22 follow-up for the maintainer's question on #3816: a Save As copy from Revit 2026.3 (`Created in: 2026.3 Update 20250908_1515(x64)`) passes `pyrevit run` and the script ran (result file: build 26.3.0.37, CLR 8.0.31). Files still as Autodesk shipped them carry pre-release or undated builds (`1515(x64)`, `20250103_1515`, `20241219_1515`, templates `20241216_1515`), and none of them are in `pyrevit revits --supported`. Reply posted on #3816.
- Workset audit on a **real office cloud project** (2026-10-22, user approved; read-only audit plus dry run; project details kept out of this public repo):
  - The audit ran cleanly on 16 worksets. The default workset (id 0) was renamed and used for levels and grids, so the "workset1" rule correctly reported "not found".
  - Name guessing: links had 2 candidates (an RVT links workset and a CAD links workset), and levels and grids had 2 as well, so the audit asked for exact names. Fixed: for Revit links, a single candidate containing "rvt" or "revit" now wins. Levels and grids still ask, because both names are plausible.
  - With exact targets, it found 5 real items: 3 levels and grids on a building workset, and 2 old links on the levels-and-grids workset. The dry run moved all 5 and rolled back; worksets were unchanged and the document was not modified.
  - **Found:** the dry run left all 5 elements **borrowed** by the user (`OwnedByCurrentUser`). A rollback does not give back elements borrowed from central. Fixed: `workset_fix.py` now returns `borrowed_by_this_run` and a `borrow_note`, and SKILL.md tells the user to click Relinquish All Mine (or Synchronize after Keep). Checked live: elements that were already borrowed are not reported, and a 1-element dry run reported `borrowed_by_this_run: [id]`.
  - Release (2026-10-24, user approved): `WorksharingUtils.RelinquishOwnership` **does** work from the agent runtime. An earlier note in this session said it did not, but that was never tested. All 5 test elements went from `OwnedByCurrentUser` to `NotOwned`, and the document stayed unmodified. Added `scripts/relinquish_borrowed.py` (`run_query`, user's OK), tested live on the borrowed and the nothing-borrowed paths. Revit's returned `RelinquishedItems` listed 0 elements while one was released, so the script reports the before/after checkout status instead.
  - Side lesson: `exec(io.open(path).read())` in IronPython left the file open inside Revit, and the next `git pull` could not replace it. Close the file explicitly (`f = open(...); try: f.read() finally: f.close()`).
- Side discovery (2026-10-22), **open**: `pyrevit run` uses the old **6.4** engine on a PC fixed with the per-user 7.0 manifest. Evidence from the CLI 7.0.0.26278 on the maintainer PC:
  - `pyrevit attached` lists only `Unnamed-363FBF8 ... Path: "C:\Program Files\pyRevit-Master" | AllUsers` for 2024.2, 2025 and 2026. The per-user 7.0 attachment that interactive Revit loads is not listed.
  - `pyrevit run` printed `Clone: Unnamed-363FBF8 | Version: "6.4.0.26100+0515" | Path: "C:\Program Files\pyRevit-Master"` and `Engine: ... Path: "C:\Program Files\pyRevit-Master\bin\netcore\engines\IPY2712PR\pyRevitLoader.dll"`. Its runner manifest loads `C:\Program Files\pyRevit-Master\bin\netcore\engines\IPY2712PR\pyRevitRunner.dll`.
  - It also printed `Product: 2026 First Customer Ship` although Revit 2026.3 ran the script.
  - Same root cause as the original 6.4-vs-7.0 problem: the admin-owned machine-wide attachment. Effect: `am-pyrevit7-setup` fixes interactive Revit, but headless `pyrevit run` (CI, batch) still runs pyRevit 6.4 code until IT removes the machine-wide 6.4 install. Users are now told: `am-doctor` reports HEADLESS_OLD_PYREVIT (info; 6 hermetic tests, 3 mutants killed, run in CI), and `am-pyrevit7-setup` explains it and ships `IT-REQUEST.md`. Still open: whether `pyrevit run` can target the per-user clone without admin (for example a per-user attach or a runner option).
- pyrevitlabs/pyRevit#3812 (non-ASCII results) was closed as completed on 2026-10-21, with no comment. When a pyRevit release includes the fix, check whether `ascii_safe` in the workset scripts is still needed.

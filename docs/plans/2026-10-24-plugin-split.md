# Plan: split archi-magic into core, revit and rhino plugins

Status: REVISED after review (rev 2), 2026-10-24. No code changes yet. PR 1 needs the user's go-ahead, and PR 2 needs a second go-ahead at the decision gate (section 3, step 3).
Owner repo: zsenarchitect/archi-magic. Base: main `398ce25`.

## Review record

| Lens | Verdict | Main findings now in this plan |
|---|---|---|
| Scheme / config / library compatibility | NEEDS WORK | Meta at `./` caches the whole repo; the rollback needs `forceRemoveDeletedPlugins` and burns the names; test from the git branch, not a local path; manifest `name` must equal the entry name; use qualified install names |
| Scale / math / blast radius | NEEDS WORK | An update that skips `/reload-plugins` leaves an empty meta with no warning (guard hook); PR 1 must soak; existing users save ~0 tokens; opt-out and a missing core are untested; the notice for partial installs |
| Existing-code audit | NEEDS WORK | The bim-viewer skill reads `mods/` at runtime; am-grill-me hard-codes `archi-magic:am-grilling`; sync-house-rules, design-templates, check-skills, check-version-bump and the CI list-skills step are root-relative; reuse `Get-DepsState` and the copy-plus-check pattern |
| Memory / priors / sequencing | NEEDS WORK | Scripts read the real `%USERPROFILE%\.claude` and `%LOCALAPPDATA%` (step 2 is not isolated); hook checks need a signed-in session; the Rhino branch must land before the split; stale user-facing paths; Revit file locks during migration |

## 1. What changes and why

Today one plugin, `archi-magic` (marketplace source `./`), ships 17 skills, the SessionStart hooks and the shared PowerShell log library. Of the skills, 13 need Revit/pyRevit, 1 needs Rhino and 3 are generic. Three more Rhino skills are being built in a worktree: `am-rhino-model-health`, `am-rhino-area-report` and `am-rhino-layer-cleanup`.

Target:

| Plugin | Source | Contents |
|---|---|---|
| `archi-magic` (meta, existing name) | `./` (unchanged, see trade-off T1) | No skills. One **guard hook** (G1). `dependencies`: archi-magic-core, archi-magic-revit, archi-magic-rhino |
| `archi-magic-core` | `./plugins/core` | am-welcome (made app-neutral), am-grilling, am-grill-me; the rules hook and the update-notice hook; shared libs; `dependencies`: superpowers, frontend-design |
| `archi-magic-revit` | `./plugins/revit` | the 13 Revit skills, including am-doctor, am-bim-viewer and am-markup-intake (it uses am-schedule-view's `render-table.ps1`, so it must stay with it); `dependencies`: archi-magic-core |
| `archi-magic-rhino` | `./plugins/rhino` | am-rhino-setup + 3 new skills; `dependencies`: archi-magic-core |

The mods and the external pins (superpowers, frontend-design, rhino-mcp) are unchanged.

**G1, guard hook in the meta.** It reads `installed_plugins.json` (from `CLAUDE_CONFIG_DIR`, falling back to `%USERPROFILE%\.claude`). If core, revit or rhino is missing or disabled, it shows a `systemMessage` with the exact fix: run `/reload-plugins`, and if they are still missing, the qualified `/plugin install archi-magic-<x>@archi-magic` lines. This covers the failure all reviewers flagged: an update that skips the reload leaves an empty meta, and the warning hook lives in the missing core.

**Why split:**
- People install what they use; for example, a Rhino-only office installs core + rhino.
- The repo shows the app boundary.
- Each app's checks live with that app.

**Token cost, measured honestly** (`claude plugin details archi-magic`, CLI 2.1.308, 2026-10-24):
- The current always-on cost is ~3,131 tokens per session: Revit ~2,520, Rhino ~220, generic ~400.
- With the 3 new Rhino skills, the full set is ~3.8k. Core + rhino is ~1.3k, and core + revit is ~2.9k.
- **Existing users save ~0**, because "install archi-magic" still means everything.

The split is justified by structure and opt-in, not tokens.

**Skill names:** `name` fields stay the same. The namespaced form changes (for example `archi-magic-revit:am-model-health`), with no alias mechanism. The repo itself uses the old form once (`am-grill-me/SKILL.md:7,11`). PR 1 removes it, and a check rejects `archi-magic:am-` anywhere.

## 2. Assumptions and how each is verified

| # | Assumption | Source | Verification |
|---|---|---|---|
| A1 | An installed plugin has nothing above its root | plugins/loading.md "Files outside the plugin directory aren't copied" | Grounded. Shared files are copied in, by one manifest-driven sync plus a check (S1) |
| A2 | Bare-name dependencies resolve within this marketplace and install transitively (meta → core → superpowers) | manifest-reference#dependencies; transitive install is only implied | Step 2(a): superpowers and frontend-design must arrive through core alone. Only then drop them from the meta |
| A3 | A manual update installs new dependencies only after `/reload-plugins`, or (worst case, ledger 0.1.0 → 0.4.1) not at all | dependencies.md; feature ledger | Step 2(b1–b3) records what is installed after each path. G1 must catch every failing path |
| A4 | A subfolder plugin's version is the repo commit (it is today for `./`: version `398ce25dd445` = gitCommitSha) | loading.md "commit SHA of the installed directory" (NOT DOCUMENTED per-folder vs repo) | Step 2(c): commits touching only `plugins/revit`, then read every version. The notice logic (U1) works either way |
| A5 | Only core has the rules and notice hooks; the meta has only G1 | hooks.md (all plugins' hooks run) | A check: exactly one rules hook and one G1. "Rules once" is measured in a **new** session (an old hook path can fire until a reload) |
| A6 | Manifest `name` equals the marketplace entry name for every plugin | manifest-reference#metadata-precedence | check-skills assertion, plus `claude plugin validate .` in CI |
| A7 | Uninstalling or disabling the meta leaves core/revit/rhino installed, so an office can switch to core + rhino | NOT DOCUMENTED | Step 2(e). Document the exact switch steps only after it is observed |
| A8 | The CLI refuses to disable or uninstall core while revit or rhino depend on it | cli-reference#plugin-disable (disable: documented; uninstall: NOT DOCUMENTED) | Step 2(f). If uninstall is allowed, am-doctor DEPS flags it, and G1 already flags a missing core |
| A9 | Rollback: remove the 3 entries, add `renames: {x: null}` and `forceRemoveDeletedPlugins: true`, and the caches go | host-marketplace#rename-or-remove-a-plugin; whether `null` counts as "renamed" or "removed" is NOT DOCUMENTED | Step 2(d) records whether the cache folders are removed. The names are then burned (renames are append-only) |

## 3. Rollout order, with rollback per step

1. **PR 1, prep (works under the flat layout and the new layout):**
   - **Shared installed-plugins lib:** move `Get-DepsState` (doctor.ps1:164-208) into `scripts/lib/am-plugins.ps1`. It resolves `CLAUDE_CONFIG_DIR` (fallback `%USERPROFILE%\.claude`) and resolves dependencies transitively from the meta. doctor, update-check, list-skills and rhino-setup use it, so no hard-coded `%USERPROFILE%\.claude` remains (doctor.ps1:47-48, rhino-setup.ps1:42,128). The DEPS fix text is updated.
   - **U1, update notice:** read `gitCommitSha` for every installed `archi-magic*` entry. Notify when any is behind the latest release, and name only the stale installed plugins. The steps include `/reload-plugins` and qualified names. One notice per day (existing cache). Tests: meta, core + rhino, core + revit, partial update.
   - **am-log.ps1:** the version lookup accepts any `archi-magic*` folder.
   - **list-skills.ps1:** lists the skills of the installed archi-magic plugins via am-plugins.ps1. The CI step uses a fixture `installed_plugins.json`.
   - **S1, one shared-files manifest:** generalise `sync-design-tokens.ps1` and `design-templates.ps1` into a single list of source → copy pairs (design tokens and theme, `am-log.ps1`, `am-plugins.ps1`, and the bim-viewer `viewer/` files the skill reads at runtime), with one sync script and one check. The check is mutation-tested.
   - **sync-house-rules.ps1, check-skills.ps1, check-version-bump.ps1:** walk `skills/` and `plugins/*/skills`. They **fail on 0 matches**. They include `plugins/*/.claude-plugin/plugin.json`. They assert the A6 names, reject `archi-magic:am-`, and (after the split) reject a root `skills/`. Each new rule is mutation-tested.
   - **am-grill-me:** use the bare `am-grilling`.
   - **am-doctor:** flag an `installPath` that is missing or partly deleted (a half-swapped cache).

   Rollback: `git revert -m 1`. No layout change.
2. **PR 1 soak + Rhino skills land.**
   - Release PR 1, update this PC, and run it. Merge the Rhino skills PR in the flat layout, so the split's `git mv` carries them.
   - The soak lasts 2 weeks, so most installs get U1 and G1-aware text before the split.
   - The user tells colleagues through the channel they read (draft: a 3-step, non-developer message, written in this PR).
3. **Decision gate (ask the user):** go on to PR 2, or stop here. Stopping is a valid end state: PR 1 already gives app-grouped docs and safer tooling.
4. **Step 2, isolated trial, before PR 2 merges:**
   - Branch `split/trial` with the full layout. Use a throwaway `CLAUDE_CONFIG_DIR`, `LOCALAPPDATA` and `-CacheDir`, and the explicit desktop CLI (`%APPDATA%\Claude\claude-code\<ver>\<hash>\claude.exe`). Add the marketplace **from git**: `plugin marketplace add zsenarchitect/archi-magic#split/trial` (a local path loads in place and gives false passes).
   - Runs:
     - (a) a fresh install;
     - (b1) update with "Update marketplace" only;
     - (b2) update, then restart without a reload;
     - (b3) the documented steps;
     - (c) revit-only commits, checking A4;
     - (d) the rollback (A9);
     - (e) uninstall the meta (A7);
     - (f) uninstall or disable core (A8).
   - The CLI commands (`install`, `update`, `list`, `details`) are run by the agent. The hook checks (rules once, U1, G1) need a signed-in session in the throwaway dir, which **the user** does.
   - Every result is recorded here. Stop and re-plan if A2, A3 or A7 surprise.
5. **PR 2, the split:**
   - `git mv` into `plugins/<x>/skills`; the hooks go to core and G1 to the meta; plugin.json and the marketplace entries.
   - CI paths: `.github/workflows/check-skills.yml` and all test paths.
   - am-welcome app-neutral, branching on the installed plugins.
   - User-facing paths: README:58,116,154,166-175; am-doctor SKILL.md:59; release.yml notes adding `/reload-plugins`. The "For AI agents" procedure gains the core + rhino and core + revit installs, with qualified names.

   Rollback: a revert PR that restores the flat layout in the meta (so the meta gets the skills back), removes the 3 entries, and adds `null` renames plus `forceRemoveDeletedPlugins: true`. The release note tells direct core/rhino installers to `/plugin install archi-magic@archi-magic`. A retry later needs new names.
6. **Migrate this PC:** close Revit and Rhino first (file locks), run the documented update, then confirm `claude plugin list`, the rules hook in a new session, U1, G1 (by disabling rhino on purpose) and `am-doctor` DEPS.

## 4. Success metrics and how they are measured

- Step 2(a): a fresh install lists archi-magic, -core, -revit, -rhino, superpowers and frontend-design, all enabled, with superpowers and frontend-design coming in through core.
- Step 2(b1–b3): every path either ends fully installed or G1 shows the fix. No path ends silently empty.
- All 20 skills are listed exactly once, under the new namespaces (sum of `claude plugin details` per plugin = the skill folders).
- In a new session: the rules block appears once. The notice appears once when behind, and not when current.
- Core + rhino always-on is below 1.5k tokens.
- CI: every check passes, and each new rule has a recorded mutation proof (break → red, legitimate change → green, nonzero assertions).
- This PC: `am-doctor` healthy, apart from the known HEADLESS info line.

## 5. Open questions

1. A4: per-folder or repo-wide version? U1 handles both. The answer only changes how often notices fire.
2. Soak length: is 2 weeks right for this team's update habits? (The user decides.)
3. Should the meta pull in rhino by default? Proposed: yes ("archi-magic" = everything), with documented core + revit and core + rhino installs for opt-out, once A7 is observed.
4. If A7 or A8 fail badly (the meta can't be removed without its dependencies, or core can be pulled out from under revit), is the split still worth it? Decided at the gate.

## 6. External dependencies

- Claude Code plugin behavior (dependencies, versions, `renames`, `forceRemoveDeletedPlugins`, `/reload-plugins`), on CLI 2.1.308 (README states 2.1.299+). It is verified only by step 2.
- GitHub release workflow (unchanged, one tag per merge).
- The user: a sign-in for the hook checks, the soak announcement, and both go-aheads.
- Ledger check: the senzhang-todo ledger at `/p/github/Personal/senzhang-todo` returned "Permission denied" from this shell, so no duplicate check was possible there. Within archi-magic `docs/`, this is the only plan for the split.

## 7. Non-goals and trade-offs

- **T1: the meta stays at `./`.** Its cache copy holds the whole repo (as today), but every existing install keeps the same name and source. Moving it to `./plugins/meta` would shrink the cache, but it changes the source of an installed plugin, which is untested. A check requires the root to have no `skills/`, `agents/` or `SKILL.md`, and only G1 in `hooks/`.
- **No skill renames** (no `am-revit-*`): users keep their habits and trigger phrases.
- **No independent per-plugin versions or release tags** in this change.
- **No symlinks for shared files** (Windows authors need Developer Mode); copies plus the S1 check are used instead.
- **Existing users gain nothing in tokens.** The benefit is structure and opt-in for new or Rhino-only installs.

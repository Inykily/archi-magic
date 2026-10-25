# Shared files (S1, docs/plans/2026-10-24-plugin-split.md): files that more than one plugin or skill
# needs at run time. An installed plugin cannot read files above its own folder, so each user gets
# a byte-identical copy. Source is the single place to edit; Copy is generated.
#   scripts/sync-shared-files.ps1  writes every Copy from its Source
#   scripts/check-skills.ps1       fails when a Copy differs from its Source or is missing
# Paths are relative to the repo root. Dot-sourced; defines $AmSharedFiles.
# Order: run scripts/sync-design-tokens.ps1 first (it updates the mod's template.html), then this.
$AmSharedFiles = @(
    # am-bim-viewer skill: build-viewer.mjs builds the page from these. The mod is the source; its own
    # tests (skills/am-bim-viewer/tests) test the source copy.
    @{ Source = 'mods/am-bim-viewer/viewer/build.mjs';       Copy = 'skills/am-bim-viewer/viewer/build.mjs' },
    @{ Source = 'mods/am-bim-viewer/viewer/template.html';   Copy = 'skills/am-bim-viewer/viewer/template.html' },
    @{ Source = 'mods/am-bim-viewer/viewer/viewer-core.mjs'; Copy = 'skills/am-bim-viewer/viewer/viewer-core.mjs' },
    @{ Source = 'mods/am-bim-viewer/viewer/demo.json';       Copy = 'skills/am-bim-viewer/viewer/demo.json' }
)

# Upstream issue draft: pyRevit MCP `capture_view` theme colors, and `run_query` TEMP folder

Status: DRAFT, NOT FILED. Recorded here per archi-magic issue #85 (triage 2026-11-03). No pyRevit issue has been filed for this yet.

## Summary

Two pyRevit MCP tool behaviors misled an agent session that compared filled region colors with color scheme colors:

1. `capture_view` shows the colors of the Revit UI theme, not the true model colors. A capture cannot be used to compare or show colors.
2. `run_query` scripts see the `%TEMP%` folder of the Revit process, not the agent's `%TEMP%` folder. A script that wrote to `%TEMP%` put the file in a Revit-side folder (`%TEMP%\<guid>\...`), and the agent looked in the wrong place first.

## Evidence

1. A fill stored as RGB 111,184,219 showed as RGB 0,89,132 in the capture. The agent redrew the region outlines with PIL from the RGB values as a workaround.
2. A script that wrote to `%TEMP%` put the file under a `<guid>` subfolder on the Revit side. Nothing in the tool description or the skills said this at the time.

Not verified: whether the color shift comes from the dark theme alone, or also from view graphics (halftone, transparency). Only one fill color was compared by number.

## Environment

- Windows 11, Revit 2026, pyRevit agent runtime, Claude Code desktop app
- Session date: 2026-11-02 (archi-magic issue #85)

## Suggested fix (upstream)

- `capture_view`: add an option to export with the light theme, or with true colors. Or state in the tool description that the capture follows the Revit UI theme.
- `run_query`: state in the tool description which TEMP folder a script sees. Better: return written file paths in the result, or give scripts one known output folder.

## What archi-magic changed instead (docs only)

- `skills/am-revit-api-docs/SKILL.md`: a new "MCP output traps" section. It says a capture follows the UI theme (read RGB from the model, not from a capture) and a script sees the Revit process `%TEMP%` (return file paths in the result).
- `skills/am-safe-change/recipes/material-colors.md`: the same capture warning in Step 8 (verify), so color checks compare model RGB values, not capture pixels.

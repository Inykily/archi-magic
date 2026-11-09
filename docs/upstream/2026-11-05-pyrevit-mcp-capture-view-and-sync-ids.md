# Upstream issue draft: pyRevit MCP `capture_view` unknown arguments and post-sync element ID warnings

Status: DRAFT, NOT FILED. Recorded here per archi-magic issue #195.

## Summary

Two pyRevit MCP behaviors gave misleading signals during a workshared Revit 2026 session:

1. **`capture_view` ignores unknown arguments and captures the active view silently.** Passing `view_id: <id>` (instead of `view: <id_or_name>`) returned a PNG of the active floor plan without raising an unknown-argument error.
2. **Post-sync run warning reports renumbered elements as "no longer exist (undone or deleted)".** After Synchronize with Central, newly created elements (such as a `SharedParameterElement` or newly placed areas) can receive new `ElementId` values when central already assigned the temporary ids to another user. Checking committed elements by `ElementId` alone reports them as deleted even when they remain in the model under the same `UniqueId` or GUID.

## Suggested fix (upstream)

- `capture_view`: reject unknown arguments with an error that names the valid parameter (`view`), or accept `view_id` as an alias. Include both the requested view and the captured view name in the text output.
- Post-run existence check: re-find committed elements by `UniqueId` (or `SharedParameterElement.Lookup(doc, guid)`) when `doc.GetElement(old_id)` returns `None`, and report `"element ids changed (likely Sync with Central)"` instead of `"undone or deleted"`.

## What archi-magic changed

- `skills/am-revit-api-docs/scripts/mcp_guards.py`: `validate_capture_view()` and `reconcile_post_sync_elements()`.
- `skills/am-safe-change/scripts/read_ownership.py` and `lib/ownership.py`: `unique_ids` and `guids` fallback lookup and `id_changed` reporting.
- `skills/am-revit-api-docs/SKILL.md`: documented both traps under "MCP output traps".

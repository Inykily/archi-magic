# -*- coding: utf-8 -*-
"""Pure texture-repath computation for the am-safe-change skill.

Runs under CPython 3 (tests, texture_repath_preview.py) and IronPython 2.7
style (no f-strings, no type annotations, no nonlocal). No Revit imports:
this module never touches the model. It turns a texture_paths audit into
a change preview, and compares a fresh audit against that preview.

The default rule from issue #90: replacement files come from this
project's folder only, never from another project's folder. The folder
is an input, so the rule holds by construction: the index is built from
that folder alone, and nothing outside it can be proposed.

Matching, per missing slot, against the folder index:
    exact  : one file with the same file name -> proposed.
    exact ambiguous: two or more files with the same name -> no
             proposal; the user picks one (listed under needs_choice).
    loose  : one file with the same stem but a different extension
             (for example .jpg vs .png) -> proposed with a non-blocking
             warning: it needs a human check.
    loose ambiguous: two or more stem matches -> no proposal.
    none   : no match -> the slot stays, listed under not_found for
             the owner hand-off note.

Audit row shape (what texture_report.py writes): {"material_id",
"material_name", "asset_id", "asset_name", "materials_on_asset",
"slot", "path", "candidates", "status"}.
"""
import os


def normalize_path(path):
    """One path -> its normalized form: "/" becomes "\\", stripped."""
    return str(path).strip().replace("/", "\\")


def basename_of(path):
    """File name of a normalized path. "C:\\tex\\oak.jpg" -> "oak.jpg"."""
    path = normalize_path(path)
    if "\\" in path:
        return path.rsplit("\\", 1)[-1]
    return path


def stem_of(path):
    """File name without its last extension. "oak.jpg" -> "oak"."""
    base = basename_of(path)
    if "." in base:
        return base.rsplit(".", 1)[0]
    return base


def build_index(file_paths):
    """A folder listing -> {"by_name": {name: [paths]},
    "by_stem": {stem: [paths]}}. Names are lower-cased: Windows file
    names do not differ by case. Each list is sorted, so proposals are
    stable.
    """
    by_name = {}
    by_stem = {}
    for path in file_paths:
        by_name.setdefault(basename_of(path).lower(), []).append(path)
        by_stem.setdefault(stem_of(path).lower(), []).append(path)
    for table in (by_name, by_stem):
        for key in table:
            table[key] = sorted(table[key])
    return {"by_name": by_name, "by_stem": by_stem}


def scan_folder(folder):
    """Every file under a folder, any depth, as full paths."""
    found = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            found.append(os.path.join(root, name))
    return sorted(found)


def propose_slot(old_path, index):
    """Proposal for one missing slot, or None with a reason.

    Returns (proposal, warning). proposal is None when nothing can be
    proposed safely. warning is None, or a non-blocking warning text
    for a loose match, or the reason a match was not proposed.
    """
    wanted = basename_of(old_path)
    exact = index["by_name"].get(wanted.lower()) or []
    if len(exact) == 1:
        return (exact[0], None)
    if len(exact) > 1:
        return (None, "Multiple files named %s in the search folder. "
                      "Pick one." % wanted)
    stem = stem_of(old_path)
    loose = [p for p in index["by_stem"].get(stem.lower(), [])
             if basename_of(p).lower() != wanted.lower()]
    if len(loose) == 1:
        return (loose[0], "Loose match: %s has the same name with a "
                          "different extension. Check it before you "
                          "apply." % basename_of(loose[0]))
    if len(loose) > 1:
        return (None, "Multiple files share the name %s with different "
                      "extensions. Pick one." % stem)
    return (None, None)


def compute_preview(audit, index, search_folder):
    """Change preview for every missing slot in a texture audit.

    Rows are per material (so the user sees every material fixed);
    steps are per (asset, slot) (so one asset edit fixes every
    material that shares it). Rows and steps share the before/after
    values, and the compare step checks rows, not steps.

    Returns the change-preview dict (see am-safe-change SKILL.md) plus
    "steps", "not_found", "needs_choice", "ownership_ids" and
    "expected_dependent_categories". A step whose materials disagree
    on the old path is a data error: it gets a blocking warning and
    no proposal, so the user re-reads instead of applying a guess.
    """
    steps = {}
    step_order = []
    warnings = []
    not_found = []
    needs_choice = []
    ownership_ids = []
    missing_rows = []
    for row in audit.get("rows") or []:
        if row.get("status") != "file_not_found":
            continue
        missing_rows.append(row)
        asset_id = row.get("asset_id")
        slot = row.get("slot") or ""
        key = (asset_id, slot)
        if key not in steps:
            steps[key] = {"asset_id": asset_id, "slot": slot,
                          "material_ids": [], "expect": row.get("path"),
                          "new_path": None, "loose": False,
                          "expectAfter": None}
            step_order.append(key)
            if asset_id not in ownership_ids:
                ownership_ids.append(asset_id)
        step = steps[key]
        if row.get("material_id") not in step["material_ids"]:
            step["material_ids"].append(row.get("material_id"))
        if normalize_path(step["expect"]) != normalize_path(row.get("path")):
            step["blocked"] = True
    # Second pass: one proposal per step, from the step's stored path.
    # A step whose materials disagree on the old path is a data error:
    # it gets a blocking warning and no proposal, so the user re-reads
    # instead of applying a guess.
    for key in step_order:
        step = steps[key]
        if step.get("blocked"):
            warnings.append({
                "row": "%s:%s" % (step["asset_id"], step["slot"]),
                "text": "Materials on this asset disagree on the stored "
                        "path. Read the model again before you apply.",
                "blocking": True})
            continue
        proposal, warning = propose_slot(step["expect"], index)
        step["new_path"] = proposal
        step["expectAfter"] = proposal
        step["loose"] = bool(proposal is not None and warning)
        if warning and proposal is not None:
            warnings.append({"row": "%s:%s" % (step["asset_id"], step["slot"]),
                             "text": warning, "blocking": False})
    rows_before = []
    rows_after = []
    for row in missing_rows:
        asset_id = row.get("asset_id")
        slot = row.get("slot") or ""
        old = row.get("path")
        step = steps[(asset_id, slot)]
        new = step["new_path"] if step["new_path"] is not None else old
        if step["new_path"] is None and not step.get("blocked"):
            proposal, warning = propose_slot(old, index)
            if warning and proposal is None:
                needs_choice.append({
                    "material_id": row.get("material_id"),
                    "material_name": row.get("material_name"),
                    "asset_id": asset_id, "slot": slot, "old_path": old,
                    "warning": warning})
            elif proposal is None:
                not_found.append({
                    "material_id": row.get("material_id"),
                    "material_name": row.get("material_name"),
                    "asset_id": asset_id, "slot": slot, "old_path": old})
        rows_before.append([asset_id, row.get("material_name"),
                            row.get("asset_name"), slot, old, old])
        rows_after.append([asset_id, row.get("material_name"),
                           row.get("asset_name"), slot, old, new])
    applied = [steps[k] for k in step_order if steps[k]["new_path"] is not None]
    return {
        "kind": "change-preview",
        "title": "Repath texture images from %s" % search_folder,
        "keyColumn": "AssetId",
        "columns": ["AssetId", "Material", "Asset", "Slot", "Old path",
                    "New path"],
        "changedColumns": ["New path"],
        "before": rows_before,
        "after": rows_after,
        "notes": ["%d slots repathed, %d slots left (no file found)."
                  % (len(applied), len(not_found) + len(needs_choice))],
        "warnings": warnings,
        "blocked": any(w.get("blocking") for w in warnings),
        "params": {"search_folder": search_folder},
        "steps": applied,
        "not_found": not_found,
        "needs_choice": needs_choice,
        "ownership_ids": ownership_ids,
        "expected_dependent_categories": ["Materials", "Views",
                                         "Keynote Tags", "Legends"],
    }


def compare_dryrun(preview, dryrun):
    """Dry-run result vs preview steps: (matches, differences).

    Dry-run rows (what apply_texture_repath.py returns) carry
    {"asset_id","slot","material_ids","before","after","status"}.
    Every preview step must have a dry-run row with the same asset and
    slot whose after value equals the step's expectAfter (compared
    normalized and case-insensitive) and whose status is "ok".
    """
    by_key = {}
    rows = dryrun.get("rows") or []
    if "result" in dryrun and "rows" not in dryrun:
        rows = dryrun["result"].get("rows") or []
    for row in rows:
        by_key[(row.get("asset_id"), row.get("slot") or "")] = row
    differences = []
    for step in preview.get("steps") or []:
        current = by_key.get((step.get("asset_id"), step.get("slot") or ""))
        if current is None:
            differences.append("asset %s slot %s: no dry-run row."
                               % (step.get("asset_id"), step.get("slot")))
        elif current.get("status") != "ok" or \
                normalize_path(current.get("after") or "").lower() != \
                normalize_path(step.get("expectAfter") or "").lower():
            differences.append("asset %s slot %s: dry run shows %s, "
                               "preview says %s."
                               % (step.get("asset_id"), step.get("slot"),
                                  current.get("after"),
                                  step.get("expectAfter")))
    return (not differences, differences)


def compare_preview(preview, verify_audit):
    """Fresh audit vs preview: (matches, differences).

    Every preview after-row that changes a path must appear in the
    fresh audit with the same material, asset and slot and the new path
    (compared normalized and case-insensitive: Windows paths do not
    differ by case). Rows the preview left unchanged are skipped. A
    changed row that is missing or still shows another path is a
    difference.
    """
    by_key = {}
    for row in verify_audit.get("rows") or []:
        by_key[(row.get("material_name"), row.get("asset_id"),
                row.get("slot") or "")] = row
    differences = []
    for before, after in zip(preview.get("before") or [],
                             preview.get("after") or []):
        asset_id, material_name, _asset, slot, _old, new = after
        if normalize_path(before[5]) == normalize_path(new):
            continue  # Row was not changed by the preview; skip it.
        current = by_key.get((material_name, asset_id, slot))
        if current is None:
            differences.append("%s / %s: no longer in the audit."
                               % (material_name, slot))
        elif normalize_path(current.get("path") or "").lower() != \
                normalize_path(new).lower():
            differences.append("%s / %s: is %s, preview says %s."
                               % (material_name, slot,
                                  current.get("path"), new))
    return (not differences, differences)

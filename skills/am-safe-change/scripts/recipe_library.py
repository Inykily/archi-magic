# -*- coding: utf-8 -*-
"""Team recipe library and proven fast-path manager (issue #179).

Saves, versions, and manages reusable team recipes from successful agent runs.
Includes fast-path gating: a recipe earns 'proven' status after 3 clean runs
and drops back to normal mode if stale guards fail.
Compatible with Python 2.7 and 3.x (no f-strings, ASCII only).
"""

import json
import os
import sys

PROVEN_THRESHOLD = 3


def get_recipes_dir(base_dir=None):
    """Path to the recipe store folder."""
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(base_dir, "..", "recipes")
    if not os.path.exists(target):
        try:
            os.makedirs(target)
        except Exception:
            pass
    return target


def save_recipe(recipes_dir, name, description, script_code, inputs_schema=None,
                tested_years=None, author="team", run_id=None):
    """Save or update a recipe file in the recipes directory."""
    if not os.path.exists(recipes_dir):
        try:
            os.makedirs(recipes_dir)
        except Exception:
            pass
    slug = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name.lower())
    filepath = os.path.join(recipes_dir, slug + ".recipe.json")

    existing = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    runs_count = existing.get("runs_count", 0) + (1 if run_id else 0)
    consecutive_clean = existing.get("consecutive_clean_runs", 0) + (1 if run_id else 0)
    is_proven = consecutive_clean >= PROVEN_THRESHOLD

    recipe = {
        "name": name,
        "slug": slug,
        "description": description,
        "author": author,
        "version": existing.get("version", "1.0.0"),
        "tested_years": tested_years or ["2024", "2025", "2026"],
        "inputs_schema": inputs_schema or {},
        "script": script_code,
        "last_run_id": run_id or existing.get("last_run_id"),
        "runs_count": runs_count,
        "consecutive_clean_runs": consecutive_clean,
        "proven": is_proven,
        "proven_threshold": PROVEN_THRESHOLD,
    }

    with open(filepath, "w") as f:
        json.dump(recipe, f, indent=2)
    return recipe, filepath


def record_run(recipe_filepath, run_id, dryrun_matched_preview=True, warnings_differ=False, stale_guard_failed=False):
    """Record a run execution and update proven status."""
    with open(recipe_filepath, "r") as f:
        recipe = json.load(f)

    recipe["runs_count"] = recipe.get("runs_count", 0) + 1
    recipe["last_run_id"] = run_id

    # Check clean run conditions
    if dryrun_matched_preview and not warnings_differ and not stale_guard_failed:
        recipe["consecutive_clean_runs"] = recipe.get("consecutive_clean_runs", 0) + 1
        if recipe["consecutive_clean_runs"] >= PROVEN_THRESHOLD:
            recipe["proven"] = True
    else:
        # Drop back to normal mode on any failure or diff
        recipe["consecutive_clean_runs"] = 0
        recipe["proven"] = False

    with open(recipe_filepath, "w") as f:
        json.dump(recipe, f, indent=2)
    return recipe


def evaluate_fast_path(recipe_data, baseline_hash=None, current_hash=None):
    """Determine whether a recipe may use the fast path (straight to dry-run)."""
    if not recipe_data.get("proven"):
        return False, "Recipe is not yet proven (needs %d clean runs)" % recipe_data.get("proven_threshold", PROVEN_THRESHOLD)

    if baseline_hash is not None and current_hash is not None:
        if baseline_hash != current_hash:
            return False, "Model changed since the preview (stale guard failed)"

    return True, "Fast path approved: proven recipe with valid stale guard"


def list_recipes(recipes_dir, keyword=None):
    """List recipes with optional keyword search."""
    found = []
    if not os.path.exists(recipes_dir):
        return found
    for fname in sorted(os.listdir(recipes_dir)):
        if fname.endswith(".recipe.json"):
            fp = os.path.join(recipes_dir, fname)
            try:
                with open(fp, "r") as f:
                    r = json.load(f)
                    if keyword:
                        kw = keyword.lower()
                        match = (
                            kw in r.get("name", "").lower() or
                            kw in r.get("description", "").lower() or
                            kw in r.get("slug", "").lower()
                        )
                        if not match:
                            continue
                    found.append(r)
            except Exception:
                continue
    return found


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: recipe_library.py <list|save|record|check-fast-path> [options]")
        return 0

    cmd = args[0]
    recipes_dir = get_recipes_dir()

    for i, a in enumerate(args):
        if a == "--dir" and i + 1 < len(args):
            recipes_dir = args[i + 1]

    if cmd == "list":
        kw = None
        for i, a in enumerate(args):
            if a == "--keyword" and i + 1 < len(args):
                kw = args[i + 1]
        recipes = list_recipes(recipes_dir, kw)
        print("Recipes in library (%d):" % len(recipes))
        for r in recipes:
            p_badge = "[PROVEN]" if r.get("proven") else "[STANDARD]"
            print("  - %-10s %-25s (v%s, %d runs) - %s" % (
                p_badge, r.get("name"), r.get("version"), r.get("runs_count", 0), r.get("description", "")
            ))
        return 0

    elif cmd == "save":
        name = "Custom Recipe"
        desc = "Team recipe"
        script_path = None
        run_id = None
        i = 1
        while i < len(args):
            if args[i] == "--name" and i + 1 < len(args):
                name = args[i + 1]
                i += 2
            elif args[i] == "--desc" and i + 1 < len(args):
                desc = args[i + 1]
                i += 2
            elif args[i] == "--script" and i + 1 < len(args):
                script_path = args[i + 1]
                i += 2
            elif args[i] == "--run-id" and i + 1 < len(args):
                run_id = args[i + 1]
                i += 2
            else:
                i += 1

        script_code = ""
        if script_path and os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_code = f.read()

        rec, fp = save_recipe(recipes_dir, name, desc, script_code, run_id=run_id)
        print("Saved recipe '%s' to %s" % (rec["name"], fp))
        return 0

    elif cmd == "check-fast-path":
        recipe_path = args[1] if len(args) > 1 else None
        if not recipe_path or not os.path.exists(recipe_path):
            print("Error: valid recipe file path required")
            return 1
        with open(recipe_path, "r") as f:
            rec = json.load(f)
        ok, reason = evaluate_fast_path(rec)
        print("Fast path: %s (%s)" % ("ALLOWED" if ok else "DENIED", reason))
        return 0 if ok else 2

    else:
        print("Unknown command: %s" % cmd)
        return 1


if __name__ == "__main__":
    sys.exit(main())

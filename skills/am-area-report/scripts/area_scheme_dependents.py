# -*- coding: utf-8 -*-
"""Area scheme dependent check and area restore helpers (issue #197).

Deleting an AreaScheme in Revit deletes every element returned by
AreaScheme.GetDependentElements(). That list can include placed Areas that
belong to a DIFFERENT AreaScheme.

This module provides:
1. analyze_scheme_dependents(): groups each scheme's dependents by category and
   by each Area's own AreaScheme, warning when deleting scheme X would delete
   areas of scheme Y (with counts per scheme and level), and reporting a
   positive control ("no cross-scheme areas; N own areas") when clean.
2. export_restore_bundle(): packs affected areas and their tags (by owner view
   UniqueId, head position, and leader state) before a delete or restore.
3. point_in_area_loops(): even-odd ray-casting across all boundary loops of an
   area so a point inside an interior hole is NOT falsely reported as covered.
4. verify_restore_guards(): checks count guard, per-area size match, parameter
   read-back, a self-test that plants one wrong value and requires 1 difference,
   and that all other areas in the model stayed unchanged.

Runs under CPython 3 and IronPython 2.7 (no f-strings).
"""

import argparse
import io
import json
import os
import sys


def analyze_scheme_dependents(schemes):
    """Inspect dependent elements of each area scheme.

    schemes: [{
        "id": int,
        "name": str,
        "dependents": [{
            "id": int,
            "category": str,
            "area_scheme_id": int (optional, for Areas),
            "area_scheme_name": str (optional, for Areas),
            "level": str (optional),
            "number": str (optional),
            "name": str (optional),
            "area_ft2": float (optional),
            "perimeter_ft": float (optional),
            "point": [x, y, z] (optional),
            "workset": str (optional),
            "parameters": dict (optional),
            "tags": list (optional)
        }]
    }]
    """
    reports = []
    findings = []

    for sc in schemes or []:
        sid = sc.get("id")
        sname = str(sc.get("name") or "")
        deps = sc.get("dependents") or []

        by_category = {}
        own_areas = []
        cross_areas = []
        cross_by_scheme = {}
        cross_by_scheme_level = {}

        for d in deps:
            cat = str(d.get("category") or "(unknown)")
            by_category[cat] = by_category.get(cat, 0) + 1
            if cat != "Areas":
                continue

            d_sid = d.get("area_scheme_id")
            d_sname = str(d.get("area_scheme_name") or "")
            is_own = False
            if d_sid is not None and sid is not None:
                is_own = (int(d_sid) == int(sid))
            elif d_sname:
                is_own = (d_sname == sname)
            else:
                is_own = True

            if is_own:
                own_areas.append(d)
            else:
                other = d_sname or ("Scheme %s" % d_sid)
                lvl = str(d.get("level") or "(no level)")
                cross_areas.append(d)
                cross_by_scheme[other] = cross_by_scheme.get(other, 0) + 1
                lvl_map = cross_by_scheme_level.setdefault(other, {})
                lvl_map[lvl] = lvl_map.get(lvl, 0) + 1

        warnings = []
        if cross_by_scheme:
            for other in sorted(cross_by_scheme.keys()):
                cnt = cross_by_scheme[other]
                lvl_parts = ["%s: %d" % (lv, c)
                             for lv, c in sorted(cross_by_scheme_level[other].items())]
                msg = ("Scheme '%s' will take %d area(s) of scheme '%s' with it (%s)."
                       % (sname, cnt, other, ", ".join(lvl_parts)))
                warnings.append(msg)
                findings.append({
                    "ruleId": "AREA-DEP-01",
                    "severity": "error",
                    "schemeId": sid,
                    "schemeName": sname,
                    "otherScheme": other,
                    "count": cnt,
                    "byLevel": cross_by_scheme_level[other],
                    "message": msg,
                })
            status_line = " ".join(warnings)
        else:
            status_line = ("No cross-scheme areas (scheme '%s' has %d own area(s))."
                           % (sname, len(own_areas)))

        reports.append({
            "id": sid,
            "name": sname,
            "total_dependents": len(deps),
            "by_category": by_category,
            "own_areas_count": len(own_areas),
            "cross_scheme_areas_count": len(cross_areas),
            "cross_by_scheme": cross_by_scheme,
            "cross_by_scheme_level": cross_by_scheme_level,
            "cross_scheme_areas": cross_areas,
            "blocked_for_delete": bool(cross_areas),
            "warnings": warnings,
            "status_line": status_line,
        })

    return {
        "schemes": reports,
        "findings": findings,
        "has_cross_scheme_risk": bool(findings),
    }


def export_restore_bundle(scheme_data):
    """Export placed areas and their tags before deleting a scheme or restoring."""
    records = []
    for d in scheme_data.get("dependents") or []:
        if d.get("category") != "Areas":
            continue
        pt = d.get("point")
        lvl = str(d.get("level") or "")
        stable_key = ""
        if pt and len(pt) >= 2:
            stable_key = "%s:%.3f,%.3f" % (lvl, float(pt[0]), float(pt[1]))
        tags = []
        for t in d.get("tags") or []:
            tags.append({
                "owner_view_unique_id": str(t.get("owner_view_unique_id") or t.get("view_unique_id") or ""),
                "tag_type_id": t.get("tag_type_id"),
                "head_position": list(t.get("head_position") or [0.0, 0.0, 0.0]),
                "has_leader": bool(t.get("has_leader", False)),
            })
        records.append({
            "original_id": d.get("id"),
            "stable_key": stable_key,
            "scheme_id": d.get("area_scheme_id"),
            "scheme_name": str(d.get("area_scheme_name") or ""),
            "level": lvl,
            "point": list(pt) if pt else None,
            "area_ft2": float(d.get("area_ft2") or 0.0),
            "perimeter_ft": float(d.get("perimeter_ft") or 0.0),
            "workset": str(d.get("workset") or ""),
            "number": str(d.get("number") or ""),
            "name": str(d.get("name") or ""),
            "parameters": dict(d.get("parameters") or {}),
            "tags": tags,
        })
    return {
        "source_scheme_id": scheme_data.get("id"),
        "source_scheme_name": scheme_data.get("name"),
        "area_count": len(records),
        "areas": records,
    }


def _point_in_single_polygon(x, y, poly):
    """Ray-casting test for a single 2D closed polygon [(x, y), ...]."""
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = float(poly[i][0]), float(poly[i][1])
        xj, yj = float(poly[j][0]), float(poly[j][1])
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def point_in_area_loops(pt_xy, loops):
    """Even-odd loop containment test across all boundary loops of an area.

    A point inside an outer loop AND inside an inner hole loop is contained in
    2 loops (even), so it lies in the hole (False), not inside the outer area.
    """
    x, y = float(pt_xy[0]), float(pt_xy[1])
    hits = 0
    for loop in loops or []:
        if _point_in_single_polygon(x, y, loop):
            hits += 1
    return (hits % 2) == 1


def compare_restored_areas(expected, actual, area_tol=0.01):
    """Compare expected area records against restored area records by stable_key."""
    by_key = dict((str(a.get("stable_key") or ""), a) for a in (actual or []))
    diffs = []
    if len(expected or []) != len(actual or []):
        diffs.append("count mismatch: expected %d, got %d" % (len(expected or []), len(actual or [])))

    for exp in expected or []:
        key = str(exp.get("stable_key") or "")
        act = by_key.get(key)
        if act is None:
            diffs.append("missing restored area at %s" % key)
            continue
        if abs(float(act.get("area_ft2") or 0.0) - float(exp.get("area_ft2") or 0.0)) > area_tol:
            diffs.append("area mismatch at %s: expected %.2f, got %.2f"
                         % (key, float(exp.get("area_ft2") or 0.0), float(act.get("area_ft2") or 0.0)))
        for field in ("number", "name", "workset"):
            if str(act.get(field) or "") != str(exp.get(field) or ""):
                diffs.append("%s mismatch at %s: expected '%s', got '%s'"
                             % (field, key, exp.get(field), act.get(field)))
        exp_params = exp.get("parameters") or {}
        act_params = act.get("parameters") or {}
        for pname, pval in sorted(exp_params.items()):
            if str(act_params.get(pname) or "") != str(pval or ""):
                diffs.append("parameter '%s' mismatch at %s: expected '%s', got '%s'"
                             % (pname, key, pval, act_params.get(pname)))
    return diffs


def verify_restore_guards(expected, restored, others_before, others_after, area_tol=0.01):
    """Run all 5 restore guards before committing a restore transaction."""
    diffs = compare_restored_areas(expected, restored, area_tol=area_tol)

    # Self-test: plant one wrong expected value and require exactly 1 difference
    self_test_ok = True
    if expected and restored and not diffs:
        planted = [dict(r) for r in expected]
        planted[0] = dict(planted[0])
        planted[0]["name"] = str(planted[0].get("name") or "") + "__PLANTED_DIFF__"
        planted_diffs = compare_restored_areas(planted, restored, area_tol=area_tol)
        self_test_ok = (len(planted_diffs) == 1)

    # Other areas unchanged check
    other_diffs = compare_restored_areas(others_before or [], others_after or [], area_tol=area_tol)

    ok = (not diffs) and self_test_ok and (not other_diffs)
    return {
        "ok": ok,
        "count_match": len(expected or []) == len(restored or []),
        "restore_diffs": diffs,
        "self_test_ok": self_test_ok,
        "other_areas_diffs": other_diffs,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check area scheme dependents before deleting a scheme.")
    ap.add_argument("input", help="Path to JSON file with area schemes and dependents")
    ap.add_argument("--out", help="Path to write report JSON")
    ap.add_argument("--export-restore", help="Path to write restore bundle for blocked schemes")
    args = ap.parse_args(argv)

    with io.open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    schemes = data if isinstance(data, list) else data.get("schemes", [])
    report = analyze_scheme_dependents(schemes)

    for sc in report["schemes"]:
        print(sc["status_line"])

    if args.out:
        with io.open(args.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(report, indent=2))

    if args.export_restore:
        bundles = [export_restore_bundle(s) for s in schemes]
        with io.open(args.export_restore, "w", encoding="utf-8") as f:
            f.write(json.dumps({"bundles": bundles}, indent=2))

    return 1 if report["has_cross_scheme_risk"] else 0


if __name__ == "__main__":
    sys.exit(main())

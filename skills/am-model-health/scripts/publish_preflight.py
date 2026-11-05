# -*- coding: utf-8 -*-
"""Publish-set preflight checker for Revit exports (issue #135).

Performs quality preflight checks on sheets and views in publish/export sets
prior to PDF, DWG, or IFC export. Flags empty sheets, missing title block
metadata, unplaced views, and visible crop regions.
Compatible with Python 2.7 and 3.x (no f-strings, ASCII only).
"""

import json
import os
import sys

REQUIRED_METADATA_PARAMS = ["Sheet Number", "Sheet Name", "Drawn By", "Checked By"]


def check_sheet_preflight(sheet):
    """Evaluate preflight rules for a single sheet dict."""
    findings = []
    sheet_num = sheet.get("sheet_number") or sheet.get("number") or "Unknown"
    sheet_id = sheet.get("id", "Unknown")

    # 1. Empty sheet check (no placed views)
    placed_views = sheet.get("placed_views", [])
    if not placed_views and not sheet.get("is_placeholder"):
        findings.append({
            "code": "PRE-01",
            "sheet_id": sheet_id,
            "sheet_number": sheet_num,
            "severity": "error",
            "message": "Empty sheet: no views are placed on this sheet",
            "fix_hint": "Place required viewports or delete empty sheet before publish",
        })

    # 2. Missing title block metadata
    params = sheet.get("parameters", {})
    for req in REQUIRED_METADATA_PARAMS:
        val = params.get(req)
        if val is None or not str(val).strip():
            findings.append({
                "code": "PRE-02",
                "sheet_id": sheet_id,
                "sheet_number": sheet_num,
                "parameter": req,
                "severity": "warning",
                "message": "Missing title block metadata: '%s' is empty" % req,
                "fix_hint": "Fill in required title block parameter '%s'" % req,
            })

    # 3. Crop boundary visibility check on placed views
    for v in placed_views:
        if isinstance(v, dict) and v.get("crop_box_visible"):
            findings.append({
                "code": "PRE-03",
                "sheet_id": sheet_id,
                "sheet_number": sheet_num,
                "view_name": v.get("name", "Unknown"),
                "severity": "warning",
                "message": "Crop boundary is visible on view '%s'" % v.get("name", "Unknown"),
                "fix_hint": "Uncheck 'Crop Region Visible' in view properties",
            })

    return findings


def evaluate_publish_preflight(sheets, unplaced_views=None):
    """Run full preflight evaluation across all sheets in publish set."""
    all_findings = []
    err_count = 0
    warn_count = 0
    info_count = 0

    for s in sheets:
        f_list = check_sheet_preflight(s)
        for f in f_list:
            sev = f.get("severity", "warning").lower()
            if sev == "error":
                err_count += 1
            elif sev == "warning":
                warn_count += 1
            else:
                info_count += 1
            all_findings.append(f)

    # 4. Check for unplaced documentation views
    if unplaced_views:
        for uv in unplaced_views:
            v_name = uv.get("name", "Unknown")
            info_count += 1
            all_findings.append({
                "code": "PRE-04",
                "view_id": uv.get("id"),
                "view_name": v_name,
                "severity": "info",
                "message": "Documentation view '%s' is not placed on any sheet" % v_name,
                "fix_hint": "Verify whether view should be added to export set",
            })

    ready = (err_count == 0)

    return {
        "sheets_count": len(sheets),
        "ready_to_publish": ready,
        "summary": {
            "errors": err_count,
            "warnings": warn_count,
            "info": info_count,
            "total_findings": len(all_findings),
        },
        "findings": all_findings,
    }


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: publish_preflight.py check --data <publish_set.json> [--out <preflight.json>]")
        return 0

    cmd = args[0]
    if cmd == "check":
        data_file = None
        out_file = None
        i = 1
        while i < len(args):
            if args[i] == "--data" and i + 1 < len(args):
                data_file = args[i + 1]
                i += 2
            elif args[i] == "--out" and i + 1 < len(args):
                out_file = args[i + 1]
                i += 2
            else:
                i += 1

        if not data_file or not os.path.exists(data_file):
            print("Error: valid --data file required")
            return 1

        with open(data_file, "r") as f:
            data = json.load(f)
            sheets = data.get("sheets", []) if isinstance(data, dict) else data
            unplaced = data.get("unplaced_views", []) if isinstance(data, dict) else []

        res = evaluate_publish_preflight(sheets, unplaced)
        out_str = json.dumps(res, indent=2)

        if out_file:
            with open(out_file, "w") as f:
                f.write(out_str)
            print("Wrote preflight report to %s (ready=%s)" % (out_file, res["ready_to_publish"]))
        else:
            print(out_str)
        return 0
    else:
        print("Unknown command: %s" % cmd)
        return 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Verify a kept change by a fresh re-read by element id (issues #256, #255).

Issue #256: a retype of 23 floors was reported done from the script's own
counts. A review the next day found other values. A report must say
"verified" only after a fresh read of the model, by element id, matches
the preview. Issue #255: a run can say "committed" and still hold an
Error in "failures". That run is "not verified" until a re-read says
otherwise.

Inputs:
- preview : the change preview (keyColumn, columns, before, after,
            optional deletions).
- reread  : a fresh read after the commit, by element id:
            {"columns": [...], "rows": [[...]], "missing": [id, ...]}
            (scripts/read_values_by_id.py returns this shape). The key
            column must be one of its columns.
- run     : optional. The run record of the real run. Its decision must
            be "committed" and "failures" must hold no Error.

Pure computation. Runs under CPython 3 and IronPython 2.7: no f-strings,
no type annotations, no nonlocal. No Revit imports.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_checks as checks  # noqa: E402


def _key(value):
    """Element ids compare as text: 123, "123" and 123.0 are one key."""
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return str(value).strip()


def _rows_by_key(columns, rows, key_column):
    if key_column not in columns:
        raise ValueError("Key column %r is not in the columns %r." % (key_column, columns))
    k = columns.index(key_column)
    out = {}
    for row in rows or []:
        out[_key(row[k])] = dict(zip(columns, row))
    return out


def _unescape(value):
    """Restore \\uXXXX text that IronPython scripts escape (see SKILL.md)."""
    if isinstance(value, str) and "\\u" in value:
        try:
            return value.encode("latin-1", "backslashreplace").decode("unicode_escape")
        except (UnicodeDecodeError, UnicodeEncodeError, AttributeError):
            return value
    return value


def same_value(expected, actual, tolerance=1e-6):
    """True when two read values are equal. Numbers use a tolerance.
    None and "" are equal (Revit returns None for an empty text value)."""
    if expected in (None, "") and actual in (None, ""):
        return True
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    try:
        return abs(float(expected) - float(actual)) <= tolerance
    except (TypeError, ValueError):
        return _unescape(expected) == _unescape(actual)


def verify(preview, reread, run=None, tolerance=1e-6):
    """Compare the fresh re-read with the preview's after rows."""
    key_column = preview.get("keyColumn") or "ElementId"
    columns = preview.get("columns") or []
    after = _rows_by_key(columns, preview.get("after"), key_column)
    before = _rows_by_key(columns, preview.get("before"), key_column)
    re_columns = reread.get("columns") or []
    found = _rows_by_key(re_columns, reread.get("rows"), key_column)
    missing_ids = set(_key(m) for m in reread.get("missing") or [])
    deletions = set(_key(d.get("id") if isinstance(d, dict) else d)
                    for d in preview.get("deletions") or [])
    shared = [c for c in columns if c in re_columns and c != key_column]
    differences = []
    missing = []
    matched = 0
    for key in sorted(after, key=lambda k: (len(k), k)):
        if key in deletions:
            continue
        if key not in found:
            missing.append(key)
            continue
        row_ok = True
        for col in shared:
            want, got = after[key].get(col), found[key].get(col)
            if same_value(want, got, tolerance):
                continue
            row_ok = False
            old = before.get(key, {}).get(col)
            note = "still the old value" if (old is not None and same_value(old, got, tolerance)
                                             and not same_value(old, want, tolerance)) else ""
            differences.append({"key": key, "column": col, "expected": want, "actual": got,
                                "note": note})
        if row_ok:
            matched += 1
    not_deleted = sorted((k for k in deletions if k in found and k not in missing_ids),
                         key=lambda k: (len(k), k))
    problems = []
    if not shared and after:
        problems.append("The re-read has none of the preview columns (%s). Read them again."
                        % ", ".join(c for c in columns if c != key_column))
    if run is not None:
        record = checks.unwrap_run(run)
        decision = record.get("decision")
        if decision != "committed":
            problems.append("The run decision is %r, not 'committed'." % decision)
        for err in checks.failure_errors(record):
            problems.append("Error in failures: %s" % err["text"])
    checked = len([k for k in after if k not in deletions])
    verified = not differences and not missing and not not_deleted and not problems
    return {"verified": verified, "checked": checked, "matched": matched,
            "differences": differences, "missing": missing, "not_deleted": not_deleted,
            "deletions": len(deletions), "problems": problems,
            "line": summary_line(verified, checked, matched, differences, missing,
                                 not_deleted, len(deletions), problems)}


def summary_line(verified, checked, matched, differences, missing, not_deleted, deletions, problems):
    """The one line that every final summary must carry."""
    if verified:
        extra = "" if not deletions else " %d deleted element(s) are gone." % deletions
        return ("Verified by re-read: %d of %d elements match the preview (by element id).%s"
                % (matched, checked, extra))
    parts = []
    differing = len(set(d["key"] for d in differences))
    if differing:
        parts.append("%d of %d elements differ from the preview" % (differing, checked))
    if missing:
        parts.append("%d not found by id" % len(missing))
    if not_deleted:
        parts.append("%d planned deletion(s) still exist" % len(not_deleted))
    parts.extend(problems)
    return "Not verified: %s." % "; ".join(p.rstrip(".") for p in parts)


def verify_text(report, limit=20):
    out = [report["line"]]
    for d in report["differences"][:limit]:
        out.append("- %s %s: expected %r, read %r%s" % (d["key"], d["column"], d["expected"],
                                                        d["actual"],
                                                        " (%s)" % d["note"] if d["note"] else ""))
    if len(report["differences"]) > limit:
        out.append("- ... %d more" % (len(report["differences"]) - limit))
    if report["missing"]:
        out.append("Not found by id: %s. After a sync or a reload, find them by level and "
                   "location, not by the saved id." % ", ".join(report["missing"][:limit]))
    if report["not_deleted"]:
        out.append("Still in the model: %s." % ", ".join(report["not_deleted"][:limit]))
    return "\n".join(out)

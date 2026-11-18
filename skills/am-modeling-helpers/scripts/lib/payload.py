# -*- coding: utf-8 -*-
"""Shared helpers for the am-modeling-helpers terminal scripts.

Runs under CPython 3 and IronPython 2.7 (no f-strings). These helpers never
talk to Revit. They read the saved result of a run_query read script and
write JSON files for the user to review.
"""
from __future__ import division, print_function

import json

try:
    TEXT = basestring  # noqa: F821  (IronPython 2.7)
except NameError:
    TEXT = str


class InputError(ValueError):
    """Bad or unusable input. The command line scripts exit with code 2."""


def unwrap(data, kind):
    """Return the read report of the expected kind.

    Accepts the bare report, a run record with "result", a "payload" JSON
    string (the read scripts put their report there), or a JSON string.
    """
    for _ in range(5):
        if isinstance(data, TEXT):
            try:
                data = json.loads(data)
            except ValueError:
                raise InputError("The read result is not JSON.")
            continue
        if not isinstance(data, dict):
            break
        if data.get("kind") == kind:
            return data
        if "error" in data:
            raise InputError("The read result holds an error: %s %s" % (
                data.get("error"), data.get("message", "")))
        if isinstance(data.get("payload"), TEXT):
            data = data["payload"]
            continue
        if "result" in data:
            data = data["result"]
            continue
        break
    raise InputError("Expected a read result of kind '%s'." % kind)


def load_read(path, kind):
    """Read a saved run_query result file and return the report."""
    try:
        with open(path, "r") as handle:
            data = json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        raise InputError("Cannot read %s: %s" % (path, exc))
    return unwrap(data, kind)


def write_json(path, data):
    with open(path, "w") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def parse_ids(text):
    """'12, 34' -> [12, 34]. Empty or None -> []."""
    if not text:
        return []
    ids = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise InputError("Element ids must be positive whole numbers: %r" % part)
        ids.append(int(part))
    return ids


def change_preview(title, columns, changed, before, after, notes=None,
                   warnings=None, **extra):
    """Build a change preview in the am-safe-change format (key column first)."""
    if len(before) != len(after):
        raise ValueError("before and after need the same rows")
    preview = {
        "kind": "change-preview",
        "title": title,
        "keyColumn": columns[0],
        "columns": list(columns),
        "changedColumns": list(changed),
        "before": before,
        "after": after,
        "notes": list(notes or []),
        "warnings": list(warnings or []),
    }
    preview["blocked"] = any(w.get("blocking") for w in preview["warnings"])
    preview.update(extra)
    return preview


def table(rows, headers):
    """Plain text table for the chat. rows are lists of values."""
    cells = [[str(h) for h in headers]] + [["" if v is None else str(v) for v in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    lines = []
    for n, row in enumerate(cells):
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))).rstrip())
        if n == 0:
            lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    return "\n".join(lines)


def pct(value):
    if value is None:
        return "?"
    return "%.0f%%" % (100.0 * value)

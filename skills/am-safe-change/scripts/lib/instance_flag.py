# -*- coding: utf-8 -*-
"""Pure computation for the instance-flag recipe (issue #250).

"Flag instances in a QA parameter": write a short value such as
    OVER +0.75 ft @2026-11-18 14:30
to a text parameter of each instance that fails a check, for example a
wall that is taller than its type's limiting height. The value is a
snapshot. The run time tells a reader how far to trust it. Every re-run
clears the flags of older runs on the elements that now pass.

Field report: the first value was long ("OVER: <height> > limit <limit>
by <excess> | <mark> <type> | <phase>"). The user asked for the compact
form "<FLAG> +<amount>" and then for the run time.

Read result shape (from read_instance_flag.py, bare or inside the run
envelope under "result"):
    {"document", "parameter", "parameter_exists": bool,
     "categories": ["OST_Walls"], "workshared": bool,
     "elements": [{"id", "category", "name", "amount": number or null,
                   "current": text or null, "status": "NotOwned" | ...,
                   "owner": text, "in_group": bool}]}
"amount" is the excess in Revit internal units (feet), or null when the
element passes the check.

Pure computation. Runs under CPython 3 and IronPython 2.7: no f-strings,
no type annotations, no nonlocal. No Revit imports.
"""

import re

FLAG_NAME = re.compile(r"^[A-Z][A-Z0-9_-]{0,15}$")
RUN_TIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
FLAG_VALUE = re.compile(r"^(?P<flag>[A-Z][A-Z0-9_-]{0,15}) \+(?P<amount>.+?) @(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2})$")
SKIP_STATUS = ("OwnedByOtherUser",)


def format_flag(flag, amount, run_time, decimals=2, unit="", scale=1.0):
    """"<FLAG> +<amount><unit> @<YYYY-MM-DD HH:MM>". amount is in feet;
    scale converts it to the display unit (12 for inches, 304.8 for mm)."""
    if not FLAG_NAME.match(flag or ""):
        raise ValueError("The flag must be 1 to 16 capital letters, digits, '-' or '_', "
                         "starting with a letter (for example OVER).")
    if not RUN_TIME.match(run_time or ""):
        raise ValueError("The run time must be 'YYYY-MM-DD HH:MM'.")
    text = ("%." + str(int(decimals)) + "f") % (float(amount) * float(scale))
    return "%s +%s%s @%s" % (flag, text, unit or "", run_time)


def parse_flag(value):
    """{"flag", "amount", "time"} for a value an earlier run wrote, else None."""
    if not value:
        return None
    m = FLAG_VALUE.match(str(value).strip())
    if not m:
        return None
    return {"flag": m.group("flag"), "amount": m.group("amount"), "time": m.group("time")}


def load_read_result(data):
    if "result" in data and "elements" not in data:
        data = data["result"]
    if data is None or "elements" not in data:
        raise ValueError("Not an instance-flag read result (no 'elements').")
    return data


def plan_flags(read, flag, run_time, decimals=2, unit="", scale=1.0, title=None):
    """The change preview for one run of the flag.

    - An element that fails the check (amount > 0) gets the new value.
    - An element that passes and holds a flag from any earlier run is
      cleared (""). A flag value is "<FLAG> +<amount> @<time>".
    - An element whose value is other text is never changed. That is a
      blocking warning: someone else uses the parameter.
    - An element that another user borrows is skipped and listed.
    """
    parameter = read.get("parameter") or ""
    if not parameter:
        raise ValueError("The read result names no parameter.")
    cols = ["ElementId", "Category", "Name", parameter]
    before, after, steps, warnings, skipped = [], [], [], [], []
    counts = {"set": 0, "cleared": 0, "unchanged": 0, "skipped": 0, "passing": 0}
    for el in sorted(read.get("elements") or [], key=lambda e: int(e["id"])):
        current = el.get("current") or ""
        amount = el.get("amount")
        fails = amount is not None and float(amount) > 0
        new = format_flag(flag, amount, run_time, decimals, unit, scale) if fails else ""
        if not fails and not current:
            counts["passing"] += 1
            continue
        if current and parse_flag(current) is None:
            warnings.append({"row": str(el["id"]), "blocking": True,
                             "text": "Element %s holds other text in %s (%r). The recipe "
                                     "changes only its own flag values. Ask the user."
                                     % (el["id"], parameter, current)})
            continue
        if new == current:
            counts["unchanged"] += 1
            continue
        if el.get("status") in SKIP_STATUS:
            counts["skipped"] += 1
            skipped.append({"id": el["id"], "owner": el.get("owner") or "",
                            "wanted": new})
            warnings.append({"row": str(el["id"]), "blocking": False,
                             "text": "Skipped: element %s is borrowed by %s. Its value stays %r."
                                     % (el["id"], el.get("owner") or "another user", current)})
            continue
        counts["set" if new else "cleared"] += 1
        row = [el["id"], el.get("category") or "", el.get("name") or ""]
        before.append(row + [current])
        after.append(row + [new])
        steps.append({"id": el["id"], "before": current, "after": new})
    notes = ["%d set, %d cleared (flags of older runs on elements that now pass), %d unchanged, "
             "%d skipped (borrowed by another user)."
             % (counts["set"], counts["cleared"], counts["unchanged"], counts["skipped"]),
             "Run time %s. The values are a snapshot: re-run the check before you trust them."
             % run_time]
    create = not read.get("parameter_exists")
    if create:
        notes.append("The parameter %r does not exist. The apply script creates it as a shared "
                     "instance text parameter (values can vary by group instance) through a "
                     "temporary shared parameter file, then restores your shared parameter "
                     "file setting." % parameter)
    blocked = any(w["blocking"] for w in warnings)
    categories = sorted(set(el.get("category") for el in read.get("elements") or [] if el.get("category")))
    return {"kind": "change-preview",
            "title": title or "Flag %s in %s" % (flag, parameter),
            "keyColumn": "ElementId", "columns": cols, "changedColumns": [parameter],
            "before": before, "after": after, "notes": notes, "warnings": warnings,
            "blocked": blocked, "steps": steps, "skipped": skipped, "counts": counts,
            "edited_categories": categories, "expected_dependent_categories": [],
            "ownership_ids": [s["id"] for s in steps],
            "params": {"parameter": parameter, "flag": flag, "run_time": run_time,
                       "create_parameter": create,
                       "categories": list(read.get("categories") or [])}}


def text_table(preview, head=10, tail=10):
    """Compact chat table: first and last rows, counts, warnings."""
    out = [preview["title"]]
    rows = list(zip(preview["before"], preview["after"]))
    shown = rows if len(rows) <= head + tail else rows[:head] + [None] + rows[-tail:]
    for pair in shown:
        if pair is None:
            out.append("  ...")
            continue
        b, a = pair
        out.append("  %s %s %s: %r -> %r" % (b[0], b[1], b[2], b[3], a[3]))
    out.extend(preview["notes"])
    for w in preview["warnings"]:
        out.append(("BLOCKING: " if w["blocking"] else "WARN: ") + w["text"])
    if preview["blocked"]:
        out.append("BLOCKED: resolve the blocking warnings first.")
    return "\n".join(out)


def compare(preview, rows):
    """Differences between the preview's after values and [[id, value], ...]."""
    want = dict((str(a[0]), a[3]) for a in preview["after"])
    got = dict((str(r[0]), r[1]) for r in rows)
    diffs = []
    for key in sorted(want, key=lambda k: (len(k), k)):
        if key not in got:
            diffs.append("%s: not in the result" % key)
        elif (want[key] or "") != (got[key] or ""):
            diffs.append("%s: expected %r, got %r" % (key, want[key], got[key]))
    for key in sorted(set(got) - set(want), key=lambda k: (len(k), k)):
        diffs.append("%s: changed, but not in the preview" % key)
    return diffs

# -*- coding: utf-8 -*-
"""Pure sheet-renumber computation for the am-safe-change skill.

Runs under IronPython 2.7 (inside Revit) and CPython 3 (tests). No f-strings,
no type annotations, no nonlocal. No Revit imports: this module never touches
the model. It only turns a list of sheets into a change preview and an ordered
list of assignment steps that keeps every sheet number unique after each step.

Sheet dict shape (what read_sheets.py returns):
    {"id": 123, "number": "A301", "name": "SECTIONS", "placeholder": False}
"""
import re

# Revit rejects these characters in a sheet number (ViewSheet.SheetNumber docs,
# 2024-2026), so the temporary prefix cannot use "~".
PROHIBITED = set("{}[]|;<>?`~")
TMP_PREFIX = "TMP-AMSC-"
COLUMNS = ["ElementId", "Sheet Number", "Sheet Name"]

_NUM_RE = re.compile(r"^(\D*?)(\d+)(.*)$")


def parse_number(text):
    """Split a sheet number into (prefix, digits, suffix).

    "A301"   -> ("A", "301", "")
    "A301a"  -> ("A", "301", "a")
    "A301.1" -> ("A", "301", ".1")
    "A-010"  -> ("A-", "010", "")
    Returns None when the text has no digits (for example "COVER").
    """
    if text is None:
        return None
    m = _NUM_RE.match(text)
    if not m:
        return None
    return (m.group(1), m.group(2), m.group(3))


def format_number(prefix, value, width, suffix):
    """Rebuild a sheet number. Keeps zero padding to the original width."""
    digits = str(value)
    if len(digits) < width:
        digits = "0" * (width - len(digits)) + digits
    return prefix + digits + suffix


_ESC_RE = re.compile(r"\\(\\|u[0-9a-fA-F]{4})")


def unescape(text):
    """Reverse the IronPython ASCII escaping done by read_sheets.py."""
    def rep(m):
        tok = m.group(1)
        if tok == "\\":
            return "\\"
        try:
            return unichr(int(tok[1:], 16))  # noqa: F821 (IronPython / Py2)
        except NameError:
            return chr(int(tok[1:], 16))
    return _ESC_RE.sub(rep, text)


def load_read_result(result):
    """Turn a read_sheets.py result (or the full run JSON) into sheet dicts."""
    if "result" in result and "sheets" not in result:
        result = result["result"]
    sheets = []
    for s in result["sheets"]:
        d = dict(s)
        if result.get("escaped"):
            d["number"] = unescape(d["number"])
            d["name"] = unescape(d["name"])
        sheets.append(d)
    return sheets


def series_of(prefix, digits):
    """Series key: prefix plus every digit except the last two (A301 -> A3)."""
    return prefix.upper() + digits[:-2]


def _key(number):
    return (number or "").strip().lower()


def select_scope(sheets, start, scope="series", include_suffixed=True,
                 include_placeholders=True, custom_ids=None):
    """Return the list of sheets that move.

    scope:
      "series" - same prefix and same series as start, numeric part >= start
      "after"  - same prefix as start, numeric part >= start (any series)
      "custom" - only the sheets whose id is in custom_ids
    """
    sp = parse_number(start)
    if sp is None:
        raise ValueError("Start number has no digits: %s" % start)
    s_prefix, s_digits, _s_suffix = sp
    s_value = int(s_digits)
    custom = set(custom_ids or [])
    picked = []
    for sh in sheets:
        if sh.get("placeholder") and not include_placeholders:
            continue
        if scope == "custom":
            if sh["id"] in custom:
                picked.append(sh)
            continue
        p = parse_number(sh["number"])
        if p is None:
            continue
        prefix, digits, suffix = p
        if prefix.upper() != s_prefix.upper():
            continue
        if suffix and not include_suffixed:
            continue
        if int(digits) < s_value:
            continue
        if scope == "series" and series_of(prefix, digits) != series_of(s_prefix, s_digits):
            continue
        picked.append(sh)
    return picked


def compute_targets(moving, step=1, keep_gaps=True):
    """Map sheet id -> new number for the moving sheets.

    keep_gaps=True : every base number goes up by step (A301, A305 -> A302, A306).
    keep_gaps=False: base numbers become consecutive, starting at the lowest
                     base + step (A301, A305 -> A302, A303).
    A suffixed number moves with its base (A301a -> A302a).
    """
    parsed = []
    for sh in moving:
        p = parse_number(sh["number"])
        if p is None:
            raise ValueError("Cannot shift a number without digits: %s" % sh["number"])
        parsed.append((sh, p))
    bases = sorted(set(int(p[1]) for _sh, p in parsed))
    remap = {}
    if keep_gaps:
        for b in bases:
            remap[b] = b + step
    else:
        first = bases[0] + step if bases else 0
        for i, b in enumerate(bases):
            remap[b] = first + i
    targets = {}
    for sh, p in parsed:
        prefix, digits, suffix = p
        targets[sh["id"]] = format_number(prefix, remap[int(digits)], len(digits), suffix)
    return targets


def order_changes(changes, step=1):
    """Order (id, old, new) changes so no step reuses a number still in use.

    step > 0 (upward): the sheet with the highest number moves first, so its
    old number is free before the sheet below takes it.
    step < 0 (downward): the sheet with the lowest number moves first, so its
    old number is free before the sheet above takes it.
    """
    def sort_key(c):
        p = parse_number(c[1])
        return (int(p[1]) if p else -1, c[1])
    return sorted(changes, key=sort_key, reverse=(step >= 0))


def simulate(sheets, steps):
    """Apply steps to a copy of the numbers. Return a list of error strings.

    Fails a step when its new number belongs to another sheet at that moment
    (case-insensitive, which is the safe side).
    """
    owner = {}
    current = {}
    for sh in sheets:
        current[sh["id"]] = sh["number"]
        owner[_key(sh["number"])] = sh["id"]
    errors = []
    for i, st in enumerate(steps):
        sid, new = st[0], st[2]
        holder = owner.get(_key(new))
        if holder is not None and holder != sid:
            errors.append("step %d: %s is still used by sheet %s" % (i + 1, new, holder))
            continue
        old = current.get(sid)
        if old is not None and owner.get(_key(old)) == sid:
            del owner[_key(old)]
        owner[_key(new)] = sid
        current[sid] = new
    return errors


def build_steps(sheets, changes, step=1):
    """Return (steps, used_temp). Steps are [id, from, to].

    First try the plain order from order_changes (highest-first for step > 0,
    lowest-first for step < 0). Only when the simulation proves that order
    fails (possible when gaps are closed) use two passes through unique
    temporary numbers ("TMP-AMSC-<id>").
    """
    ordered = [[c[0], c[1], c[2]] for c in order_changes(changes, step)]
    if not simulate(sheets, ordered):
        return ordered, False
    steps = []
    for c in changes:
        steps.append([c[0], c[1], "%s%s" % (TMP_PREFIX, c[0])])
    for c in changes:
        steps.append([c[0], "%s%s" % (TMP_PREFIX, c[0]), c[2]])
    return steps, True


def compute_shift(sheets, start, step=1, scope="series", keep_gaps=True,
                  include_suffixed=True, include_placeholders=True,
                  custom_ids=None, title=None):
    """Compute the full change preview (shared change-preview contract)."""
    moving = select_scope(sheets, start, scope, include_suffixed,
                          include_placeholders, custom_ids)
    targets = compute_targets(moving, step, keep_gaps)
    moving_ids = set(sh["id"] for sh in moving)
    by_id = dict((sh["id"], sh) for sh in sheets)

    warnings = []
    # Collisions with sheets that do not move (placeholders count too).
    static_numbers = {}
    for sh in sheets:
        if sh["id"] not in moving_ids:
            static_numbers[_key(sh["number"])] = sh
    seen_targets = {}
    sp = parse_number(start)
    for sid in sorted(targets, key=lambda i: by_id[i]["number"]):
        new = targets[sid]
        hit = static_numbers.get(_key(new))
        if hit is not None:
            warnings.append({"row": str(sid), "blocking": True,
                             "text": "%s -> %s collides with sheet %s '%s', which is not in scope." %
                                     (by_id[sid]["number"], new, hit["number"], hit["name"])})
        bad = sorted(set(ch for ch in new if ch in PROHIBITED))
        if bad:
            warnings.append({"row": str(sid), "blocking": True,
                             "text": "%s contains characters Revit rejects: %s" %
                                     (new, " ".join(bad))})
        if _key(new) in seen_targets:
            warnings.append({"row": str(sid), "blocking": True,
                             "text": "%s and sheet %s both get %s." %
                                     (by_id[sid]["number"], seen_targets[_key(new)], new)})
        seen_targets[_key(new)] = by_id[sid]["number"]
        op = parse_number(by_id[sid]["number"])
        np_ = parse_number(new)
        if len(np_[1]) > len(op[1]):
            warnings.append({"row": str(sid), "blocking": False,
                             "text": "%s -> %s adds a digit." % (by_id[sid]["number"], new)})
        if scope == "series" and series_of(np_[0], np_[1]) != series_of(sp[0], sp[1]):
            warnings.append({"row": str(sid), "blocking": False,
                             "text": "%s -> %s leaves the %sxx series." %
                                     (by_id[sid]["number"], new, series_of(sp[0], sp[1]))})
        if by_id[sid].get("placeholder"):
            warnings.append({"row": str(sid), "blocking": False,
                             "text": "%s is a placeholder sheet (no drawing)." % by_id[sid]["number"]})

    changes = [(sid, by_id[sid]["number"], targets[sid]) for sid in targets
               if targets[sid] != by_id[sid]["number"]]
    blocked = any(w["blocking"] for w in warnings)
    steps, used_temp = ([], False) if blocked else build_steps(sheets, changes, step)
    if steps:
        errs = simulate(sheets, steps)
        if errs:
            raise RuntimeError("Internal ordering error: %s" % "; ".join(errs))

    def sort_rows(sh):
        p = parse_number(sh["number"])
        if p is None:
            return (sh["number"].upper(), -1, "")
        return (p[0].upper(), int(p[1]), p[2])

    before, after = [], []
    for sh in sorted(sheets, key=sort_rows):
        before.append([sh["id"], sh["number"], sh["name"]])
        after.append([sh["id"], targets.get(sh["id"], sh["number"]), sh["name"]])

    params = {"start": start, "step": step, "scope": scope, "keep_gaps": keep_gaps,
              "include_suffixed": include_suffixed,
              "include_placeholders": include_placeholders}
    notes = [
        "Scope: %s from %s, step %+d, gaps %s, suffixed numbers %s, placeholders %s." % (
            scope, start, step, "kept" if keep_gaps else "closed",
            "move with their base" if include_suffixed else "stay",
            "included" if include_placeholders else "excluded"),
        "%d of %d sheets change." % (len(changes), len(sheets)),
        "Order: %s." % ("two passes through temporary numbers" if used_temp
                         else "%s number first, no temporary numbers" % (
                             "lowest" if step < 0 else "highest")),
    ]
    if blocked:
        notes.append("BLOCKED: resolve the blocking warnings before apply.")
    return {
        "kind": "change-preview",
        "title": title or ("Shift sheet numbers from %s by %+d" % (start, step)),
        "keyColumn": "ElementId",
        "columns": list(COLUMNS),
        "changedColumns": ["Sheet Number"],
        "before": before,
        "after": after,
        "notes": notes,
        "warnings": warnings,
        "blocked": blocked,
        "params": params,
        "steps": steps,
        # Views on a sheet show the sheet number, so they regenerate when
        # a sheet number changes (issue #28).
        "expected_dependent_categories": ["Views"],
    }


def preview_counts(preview):
    changed = sum(1 for b, a in zip(preview["before"], preview["after"]) if b[1] != a[1])
    return {"changed": changed, "unchanged": len(preview["before"]) - changed,
            "warnings": len(preview["warnings"]),
            "blocking": sum(1 for w in preview["warnings"] if w.get("blocking"))}


def compare(preview, actual_rows):
    """Compare the preview's after state with actual [id, number, ...] rows.

    Returns a list of difference strings. Empty list = matches preview.
    """
    want = dict((r[0], r[1]) for r in preview["after"])
    got = dict((r[0], r[1]) for r in actual_rows)
    diffs = []
    for sid in sorted(want):
        if sid not in got:
            diffs.append("sheet %s: missing in actual result" % sid)
        elif got[sid] != want[sid]:
            diffs.append("sheet %s: expected %s, got %s" % (sid, want[sid], got[sid]))
    for sid in sorted(got):
        if sid not in want:
            diffs.append("sheet %s: not in preview (%s)" % (sid, got[sid]))
    return diffs


def text_table(preview, edge=10):
    """Compact markdown table of changed rows (first/last `edge`) for chat."""
    rows = [(b, a) for b, a in zip(preview["before"], preview["after"]) if b[1] != a[1]]
    c = preview_counts(preview)
    out = ["| ElementId | Old number | New number | Sheet name |", "|---|---|---|---|"]
    shown = rows if len(rows) <= 2 * edge else rows[:edge] + [None] + rows[-edge:]
    for r in shown:
        if r is None:
            out.append("| ... | ... | ... | %d more rows |" % (len(rows) - 2 * edge))
        else:
            out.append("| %s | %s | %s | %s |" % (r[0][0], r[0][1], r[1][1], r[0][2]))
    out.append("")
    out.append("Changed: %d. Unchanged: %d. Warnings: %d (blocking: %d)." % (
        c["changed"], c["unchanged"], c["warnings"], c["blocking"]))
    for w in preview["warnings"]:
        out.append("- %s%s" % ("BLOCKING: " if w.get("blocking") else "", w["text"]))
    return "\n".join(out)

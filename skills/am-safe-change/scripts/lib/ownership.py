# -*- coding: utf-8 -*-
"""Worksharing ownership check for the am-safe-change skill (issue #97).

In a workshared model, Revit refuses to change an element that another
user borrows. The refusal rolls back the whole run, after the user has
approved the preview. This module turns a read_ownership.py result into:

- a pre-check: which target elements another user owns, with the owner
  name, as one line and as blocking warnings in the change preview;
- a post-run report: which elements the current user now borrows,
  counted by category, with the Synchronize with Central hand-off.

Pure computation. Runs under CPython 3 and IronPython 2.7: no f-strings,
no type annotations, no nonlocal. No Revit imports.

read_ownership.py result shape (bare or inside the run envelope under
"result"):
    {"workshared": true, "user": "jdoe",
     "elements": [{"id": 123, "exists": true, "status": "OwnedByOtherUser",
                   "owner": "asmith", "updates": "CurrentWithCentral",
                   "category": "Views", "name": "Level 1"}],
     "scan": {"categories": ["Views"], "checked": 1700, "partial": false},
     "scan_borrowed": [{"id": 456, "category": "Views", "name": "..."}]}
"status" is the WorksharingUtils.GetCheckoutStatus name. "updates" is
the WorksharingUtils.GetModelUpdatesStatus name (or "" if unknown).
"""

SOURCE = "ownership"  # marks the notes and warnings this module adds


def unwrap(data):
    """The read result dict, bare or inside the run envelope."""
    if "result" in data and "elements" not in data and "workshared" not in data:
        data = data["result"]
    if data is None:
        raise ValueError("The ownership read has no result (check status and error).")
    return data


def target_ids(preview, extra=None):
    """Element ids that the apply script edits, in order, without repeats.

    preview["ownership_ids"], when present, wins (for a recipe whose
    steps do not name the edited element). Otherwise each step gives
    one id: a list step [id, from, to] gives its first item, a dict
    step gives "id", or "sheet_id" when it adds a view to a sheet.
    Ids that a step only reads or copies (a source view, a type) are
    not targets, so a teammate who borrows them does not block the run.
    """
    ids = []
    if preview.get("ownership_ids") is not None:
        ids.extend(preview["ownership_ids"])
    else:
        for st in preview.get("steps") or []:
            if isinstance(st, (list, tuple)) and st:
                ids.append(st[0])
            elif isinstance(st, dict):
                if "id" in st:
                    ids.append(st["id"])
                elif "sheet_id" in st:
                    ids.append(st["sheet_id"])
    ids.extend(extra or [])
    out, seen = [], set()
    for i in ids:
        i = int(i)
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def check(read):
    """Pre-check summary of the target elements.

    Returns a dict with keys: workshared, total, others ([{id, owner,
    category, name}]), mine, not_owned, missing ([id]), updated
    ([id], UpdatedInCentral), blocked, line (one sentence).
    """
    read = unwrap(read)
    if not read.get("workshared"):
        return {"workshared": False, "total": 0, "others": [], "mine": 0,
                "not_owned": 0, "missing": [], "updated": [], "blocked": False,
                "line": "The model is not workshared. No ownership check is needed."}
    els = read.get("elements") or []
    others, missing, updated = [], [], []
    mine = not_owned = 0
    for e in els:
        if not e.get("exists", True):
            missing.append(e["id"])
            continue
        status = e.get("status")
        if status == "OwnedByOtherUser":
            others.append({"id": e["id"], "owner": e.get("owner") or "another user",
                           "category": e.get("category", ""), "name": e.get("name", "")})
        elif status == "OwnedByCurrentUser":
            mine += 1
        else:
            not_owned += 1
        if e.get("updates") == "UpdatedInCentral":
            updated.append(e["id"])
    total = len(els) - len(missing)
    line = "%d of %d elements owned by others." % (len(others), total)
    if others:
        line ="%d of %d elements owned by others. Owners: %s." % (
            len(others), total, _owner_counts(others))
    return {"workshared": True, "total": total, "others": others, "mine": mine,
            "not_owned": not_owned, "missing": missing, "updated": updated,
            "blocked": bool(others or updated), "line": line}


def _owner_counts(others):
    """'asmith (3), bjones (1)' sorted by count, largest first."""
    counts = {}
    for o in others:
        counts[o["owner"]] = counts.get(o["owner"], 0) + 1
    names = sorted(counts, key=lambda n: (-counts[n], n))
    return ", ".join("%s (%d)" % (n, counts[n]) for n in names)


def annotate(preview, summary):
    """A copy of the preview with the ownership line and warnings.

    Adds one line to "notes", one blocking warning for each element that
    another user owns or that central has updated, and the "ownership"
    key. Sets "blocked" when a blocking warning exists. Running it again
    replaces the earlier ownership notes and warnings.
    """
    p = dict(preview)
    notes = [n for n in p.get("notes") or [] if not str(n).startswith("Ownership: ")]
    notes.append("Ownership: " + summary["line"])
    warnings = [w for w in p.get("warnings") or []
                if not (isinstance(w, dict) and w.get("source") == SOURCE)]
    for o in summary["others"]:
        warnings.append({"row": str(o["id"]), "source": SOURCE, "blocking": True,
                         "text": "%s borrows this element (%s %s). Revit refuses "
                                 "the change. Ask %s to synchronize and relinquish, "
                                 "or leave the element out."
                                 % (o["owner"], o["category"], o["name"], o["owner"])})
    for i in summary["updated"]:
        warnings.append({"row": str(i), "source": SOURCE, "blocking": True,
                         "text": "Central has a newer version of this element. "
                                 "Click Collaborate > Reload Latest, then read again."})
    p["notes"] = notes
    p["warnings"] = warnings
    p["blocked"] = bool(p.get("blocked")) or summary["blocked"]
    p["ownership"] = {"checked": summary["total"],
                      "owned_by_others": summary["others"],
                      "updated_in_central": summary["updated"]}
    return p


def borrowed(read):
    """Post-run report: what the current user borrows now.

    Combines the target elements with status OwnedByCurrentUser and the
    "scan_borrowed" list (dependent elements in the scanned categories).
    Returns a dict with keys: workshared, count, by_category ([(category,
    count)], largest first), partial, line.
    """
    read = unwrap(read)
    if not read.get("workshared"):
        return {"workshared": False, "count": 0, "by_category": [], "partial": False,
                "line": "The model is not workshared. Save the model."}
    seen = {}
    for e in read.get("elements") or []:
        if e.get("exists", True) and e.get("status") == "OwnedByCurrentUser":
            seen[e["id"]] = e.get("category") or "(no category)"
    for e in read.get("scan_borrowed") or []:
        seen[e["id"]] = e.get("category") or "(no category)"
    counts = {}
    for cat in seen.values():
        counts[cat] = counts.get(cat, 0) + 1
    rows = [(c, counts[c]) for c in sorted(counts, key=lambda c: (-counts[c], c))]
    partial = bool((read.get("scan") or {}).get("partial"))
    if rows:
        line = ("You now borrow %d elements: %s. Synchronize with Central and "
                "tick Borrowed Elements to give them back."
                % (len(seen), ", ".join("%s %d" % r for r in rows)))
    else:
        line = "You borrow none of the checked elements."
    if partial:
        line += (" The scan stopped at its element limit, so the real count "
                 "can be higher.")
    return {"workshared": True, "count": len(seen), "by_category": rows,
            "partial": partial, "line": line}


def text_table(summary, limit=20):
    """Compact text of the pre-check, for chat."""
    out = [summary["line"]]
    if summary["others"]:
        out.append("ElementId | Owner | Category | Name")
        for o in summary["others"][:limit]:
            out.append("%s | %s | %s | %s" % (o["id"], o["owner"], o["category"], o["name"]))
        if len(summary["others"]) > limit:
            out.append("... and %d more." % (len(summary["others"]) - limit))
    if summary["updated"]:
        out.append("Updated in central (Reload Latest first): %s."
                   % ", ".join(str(i) for i in summary["updated"]))
    if summary["missing"]:
        out.append("Not in the model: %s." % ", ".join(str(i) for i in summary["missing"]))
    if summary["workshared"]:
        out.append("Borrowed by you already: %d. Not owned: %d."
                   % (summary["mine"], summary["not_owned"]))
    return "\n".join(out)

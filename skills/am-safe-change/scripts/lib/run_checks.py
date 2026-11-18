# -*- coding: utf-8 -*-
"""Content checks for a dry run, and the change-list review (issues #256, #255).

Issue #256: dry runs checked only counts. These defects passed a dry run
and were committed:
- new elements about two storeys above the level, out of the plan's view
  range (a Z offset added twice);
- 118 keynote tags with empty text;
- 70 copied tags that kept the template tag's leader end;
- floor areas read before doc.Regenerate() (0.0), reported as correct;
- 87 modified keynote tags and some uncategorized elements, called
  "regeneration" with no check.
Issue #255: a run returned decision "committed" with an Error-severity
entry in "failures". Nobody re-read the model.

This module checks the CONTENT of a dry run, not only the counts.

Content shape (the apply script returns it inside its result, after
doc.Regenerate(); scripts/dry_run_content.py builds it inside Revit):
    {"regenerated": true,
     "view": {"id", "name",
              "view_range": {"bottom": z or null, "top": z or null},
              "crop": null or {"origin": [x, y, z], "basis_x": [..],
                               "basis_y": [..], "min": [x, y, z],
                               "max": [x, y, z]}},
     "elements": [{"id", "category", "name",
                   "bbox": {"min": [x, y, z], "max": [x, y, z]} or null,
                   "hidden": false}],
     "tags": [{"id", "category", "text",
               "has_leader": bool, "leader_ends": [[x, y, z], ...],
               "host_ids": [id, ...],
               "host_boxes": [{"min": [..], "max": [..]}, ...]}],
     "values": [{"id", "name", "value"}]}
All lengths are Revit internal feet. "bottom" and "top" are absolute
elevations of the plan's view depth and top clip plane. null means
"no limit" (an unlimited view range, or not a plan).

Pure computation. Runs under CPython 3 and IronPython 2.7: no f-strings,
no type annotations, no nonlocal. No Revit imports.
"""

# Category names that are annotation. Revit names every tag category
# "... Tags", so a name that ends in "Tags" is also an annotation.
ANNOTATION_CATEGORIES = (
    "text notes", "dimensions", "generic annotations", "revision clouds",
    "spot elevations", "spot coordinates", "spot slopes", "keynote tags",
    "material tags", "multi-category tags", "room tags", "area tags")

NO_CATEGORY = "(no category)"
EMPTY_TEXTS = ("", "?")


def is_annotation(category):
    """True for a tag, text, dimension or other annotation category."""
    if not category:
        return False
    name = str(category).strip().lower()
    return name.endswith("tags") or name in ANNOTATION_CATEGORIES


def _warn(rows, element_id, text, blocking=False):
    rows.append({"id": element_id, "text": text, "blocking": bool(blocking)})


def _xyz(value):
    if value is None:
        return None
    return [float(value[0]), float(value[1]), float(value[2]) if len(value) > 2 else 0.0]


def _corners(box):
    lo, hi = _xyz(box["min"]), _xyz(box["max"])
    out = []
    for x in (lo[0], hi[0]):
        for y in (lo[1], hi[1]):
            for z in (lo[2], hi[2]):
                out.append([x, y, z])
    return out


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _fmt(value):
    return "%.2f" % value


def to_crop_local(crop, point):
    """(x, y) of a world point in the crop box frame."""
    rel = _sub(_xyz(point), _xyz(crop["origin"]))
    return _dot(rel, _xyz(crop["basis_x"])), _dot(rel, _xyz(crop["basis_y"]))


def outside_crop(crop, box, tolerance=0.0):
    """True when the box is fully outside the crop region (in plan)."""
    local = [to_crop_local(crop, p) for p in _corners(box)]
    xs = [p[0] for p in local]
    ys = [p[1] for p in local]
    lo, hi = _xyz(crop["min"]), _xyz(crop["max"])
    return (max(xs) < lo[0] - tolerance or min(xs) > hi[0] + tolerance
            or max(ys) < lo[1] - tolerance or min(ys) > hi[1] + tolerance)


def visibility_warnings(view, elements, tolerance=0.01):
    """One warning for each new element that the target view cannot show.

    Checks the view range (plans) and the crop region. An element with
    no model box, or hidden in the view, also gets a warning.
    """
    rows = []
    view = view or {}
    vr = view.get("view_range") or {}
    bottom, top = vr.get("bottom"), vr.get("top")
    crop = view.get("crop")
    name = view.get("name") or view.get("id")
    for el in elements or []:
        eid = el.get("id")
        label = "%s %s" % (el.get("category") or "Element", eid)
        if el.get("hidden"):
            _warn(rows, eid, "%s is hidden in view %s." % (label, name))
        box = el.get("bbox")
        if not box:
            _warn(rows, eid, "%s has no model box. Check it in view %s." % (label, name))
            continue
        lo, hi = _xyz(box["min"]), _xyz(box["max"])
        if bottom is not None and hi[2] < float(bottom) - tolerance:
            _warn(rows, eid, "%s is below the view range of %s: its top is %s ft under the bottom."
                  % (label, name, _fmt(float(bottom) - hi[2])))
        if top is not None and lo[2] > float(top) + tolerance:
            _warn(rows, eid, "%s is above the view range of %s: its base is %s ft over the top."
                  % (label, name, _fmt(lo[2] - float(top))))
        if crop and outside_crop(crop, box, tolerance):
            _warn(rows, eid, "%s is outside the crop region of %s." % (label, name))
    return rows


def tag_text_warnings(tags):
    """One warning for each tag or note with empty text (or Revit's "?")."""
    rows = []
    for tag in tags or []:
        text = tag.get("text")
        if text is None or str(text).strip() in EMPTY_TEXTS:
            _warn(rows, tag.get("id"), "%s %s has empty text (%s)."
                  % (tag.get("category") or "Tag", tag.get("id"),
                     "none" if text is None else repr(str(text).strip())))
    return rows


def _plan_distance_to_box(point, box):
    """Distance in plan (XY) from a point to a box. 0 inside the box."""
    p, lo, hi = _xyz(point), _xyz(box["min"]), _xyz(box["max"])
    dx = max(lo[0] - p[0], 0.0, p[0] - hi[0])
    dy = max(lo[1] - p[1], 0.0, p[1] - hi[1])
    return (dx * dx + dy * dy) ** 0.5


def leader_warnings(tags, max_distance=3.0, same_point=0.001):
    """Leader ends far from their host, and one leader end shared by many tags.

    max_distance : the largest plan distance (ft) from a leader end to
                   the nearest host box.
    same_point   : two leader ends closer than this (ft) are one point.
    """
    rows = []
    groups = {}
    for tag in tags or []:
        if not tag.get("has_leader"):
            continue
        tid = tag.get("id")
        boxes = [b for b in (tag.get("host_boxes") or []) if b]
        for end in tag.get("leader_ends") or []:
            if end is None:
                continue
            key = tuple(int(round(c / same_point)) for c in _xyz(end)[:2])
            groups.setdefault(key, []).append(tag)
            if not boxes:
                _warn(rows, tid, "%s %s has a leader but no host box to check it against."
                      % (tag.get("category") or "Tag", tid))
                continue
            dist = min(_plan_distance_to_box(end, b) for b in boxes)
            if dist > max_distance:
                _warn(rows, tid, "%s %s: the leader ends %s ft from its host (limit %s ft)."
                      % (tag.get("category") or "Tag", tid, _fmt(dist), _fmt(max_distance)))
    for key in sorted(groups):
        members = groups[key]
        hosts = set(tuple(sorted(str(h) for h in (t.get("host_ids") or []))) for t in members)
        if len(members) > 1 and len(hosts) > 1:
            ids = ", ".join(str(t.get("id")) for t in members[:10])
            more = "" if len(members) <= 10 else " and %d more" % (len(members) - 10)
            _warn(rows, members[0].get("id"),
                  "%d tags of different hosts share one leader end: %s%s. A copied tag kept "
                  "the leader end of its template." % (len(members), ids, more))
    return rows


def value_warnings(values, regenerated):
    """Computed values (area, length, volume) must be read after doc.Regenerate()."""
    rows = []
    if values and not regenerated:
        _warn(rows, None, "The script read computed values before doc.Regenerate(). Call "
              "doc.Regenerate() first, then read them again.", blocking=True)
    for row in values or []:
        value = row.get("value")
        number = None
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = None
        if value is None or value == "" or (number is not None and abs(number) < 1e-9):
            _warn(rows, row.get("id"), "%s of element %s reads %s. Check that the element is "
                  "complete and that the value was read after doc.Regenerate()."
                  % (row.get("name") or "Value", row.get("id"),
                     "nothing" if value in (None, "") else value))
    return rows


def content_report(content, max_leader_ft=3.0):
    """All content checks for one dry-run content dict."""
    content = content or {}
    warnings = []
    warnings += visibility_warnings(content.get("view"), content.get("elements"))
    warnings += tag_text_warnings(content.get("tags"))
    warnings += leader_warnings(content.get("tags"), max_leader_ft)
    warnings += value_warnings(content.get("values"), content.get("regenerated"))
    counts = {"elements": len(content.get("elements") or []),
              "tags": len(content.get("tags") or []),
              "values": len(content.get("values") or [])}
    return {"counts": counts, "warnings": warnings,
            "blocking": any(w["blocking"] for w in warnings)}


def content_text(report):
    """Chat text for content_report()."""
    c = report["counts"]
    out = ["Content checks: %d new elements, %d tags, %d computed values."
           % (c["elements"], c["tags"], c["values"])]
    if not report["warnings"]:
        out.append("No content problems found.")
    for w in report["warnings"]:
        out.append(("STOP: " if w["blocking"] else "WARN: ") + w["text"])
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Run envelope: change list and failures


def unwrap_run(data):
    """The run record dict: bare, or under "response" (a saved bridge reply)."""
    if isinstance(data, dict) and isinstance(data.get("response"), dict):
        return data["response"]
    return data or {}


def failure_errors(run):
    """Entries in "failures" with severity Error (or worse). Issue #255.

    A run can return decision "committed" and still hold an Error, for
    example "You now own the element, but your file is out of date". The
    edit may not have reached the model. Treat it as a stop.
    """
    run = unwrap_run(run)
    out = []
    for entry in run.get("failures") or []:
        if isinstance(entry, dict):
            severity = entry.get("severity") or entry.get("Severity") or entry.get("level") or ""
            text = (entry.get("description") or entry.get("message") or entry.get("text")
                    or entry.get("Description") or "")
        else:
            severity, text = "", entry
        sev = str(severity).strip().lower()
        if sev in ("error", "documentcorruption", "document_corruption") or (
                not sev and str(text).lower().startswith("error")):
            out.append({"severity": str(severity) or "Error", "text": str(text)})
    return out


def failures_text(run):
    """One line per Error, or one line that says there is none."""
    run = unwrap_run(run)
    errors = failure_errors(run)
    if not errors:
        return "No Error in failures."
    out = ["STOP: the run (decision: %s) has %d Error-severity failure(s). Do not report the "
           "change as done. Re-read the model and tell the user." % (run.get("decision"), len(errors))]
    for e in errors:
        out.append("ERROR: %s" % e["text"])
    return "\n".join(out)


def _change_rows(changes, kind):
    """Rows of changes[kind] as dicts with id, category, name."""
    out = []
    for row in changes.get(kind) or []:
        if isinstance(row, dict):
            out.append({"id": row.get("id", row.get("element_id")),
                        "category": row.get("category") or NO_CATEGORY,
                        "name": row.get("name") or ""})
        else:
            out.append({"id": row, "category": None, "name": ""})
    return out


def _by_category(changes):
    """{category: count} over added, modified and deleted."""
    raw = changes.get("by_category") or {}
    out = {}
    nested = any(k in raw for k in ("added", "modified", "deleted")) and all(
        isinstance(v, dict) for v in raw.values())
    parts = raw.values() if nested else [raw]
    for part in parts:
        for cat, n in part.items():
            out[cat or NO_CATEGORY] = out.get(cat or NO_CATEGORY, 0) + int(n)
    if not out:
        for kind in ("added", "modified", "deleted"):
            for row in _change_rows(changes, kind):
                if row["category"] is not None:
                    out[row["category"]] = out.get(row["category"], 0) + 1
    return out


def review_change_list(run, preview, annotations=None):
    """Read the change list of a dry run (issue #256, point 2).

    run         : the dry-run record (with "changes").
    preview     : the change preview. Expected categories are
                  "edited_categories" + "expected_dependent_categories".
    annotations : [{"id", "category", "before", "after"}], the text of
                  each changed annotation before and after the change.

    Every modified, added or deleted annotation must be named, with its
    text before and after. A category the plan did not expect is a stop,
    not "regeneration". So are uncategorized elements, unless the preview
    lists "(no category)".
    """
    run = unwrap_run(run)
    changes = run.get("changes") or {}
    preview = preview or {}
    expected = set(preview.get("edited_categories") or []) | set(
        preview.get("expected_dependent_categories") or [])
    by_cat = _by_category(changes)
    stops = []
    unexpected = sorted(c for c in by_cat if c not in expected)
    for cat in unexpected:
        if cat == NO_CATEGORY:
            stops.append("%d uncategorized element(s) changed. Name them (read their class and "
                         "owner view) before you apply." % by_cat[cat])
        else:
            stops.append("Unexpected category: %s (%d). The plan does not expect it. This is "
                         "a stop, not regeneration." % (cat, by_cat[cat]))
    changed_annotations = []
    for kind in ("added", "modified", "deleted"):
        for row in _change_rows(changes, kind):
            if row["category"] is not None and is_annotation(row["category"]):
                row = dict(row)
                row["change"] = kind
                changed_annotations.append(row)
    named = {}
    for row in annotations or []:
        named[str(row.get("id"))] = row
    unnamed = [r for r in changed_annotations if str(r["id"]) not in named]
    annotation_cats = sorted(set(c for c in by_cat if is_annotation(c)))
    if annotation_cats and not changed_annotations and not annotations:
        stops.append("The dry run changed %s, but the change list has no element ids for them. "
                     "Read the ids, then name every annotation with its text before and after."
                     % ", ".join(annotation_cats))
    if unnamed:
        stops.append("%d changed annotation(s) have no before/after text: %s. Read their text "
                     "and show it to the user." % (len(unnamed), ", ".join(str(r["id"]) for r in unnamed[:20])))
    text_changes = []
    for key in sorted(named, key=lambda k: (len(k), k)):
        row = named[key]
        before, after = row.get("before"), row.get("after")
        if before != after:
            text_changes.append(row)
    return {"by_category": by_cat, "unexpected": unexpected,
            "annotations": [named[k] for k in sorted(named, key=lambda k: (len(k), k))],
            "unnamed": unnamed, "text_changes": text_changes, "stops": stops,
            "errors": failure_errors(run), "blocking": bool(stops) or bool(failure_errors(run))}


def annotation_rows(before_read, after_tags, text_column="Text"):
    """Join the text before (a read_values_by_id.py result) and after
    (the "tags" of a second dry run's content) into review rows.

    before_read : {"columns": [...], "rows": [[...]], "missing": [...]}
                  with an "ElementId" column and a text column.
    after_tags  : [{"id", "category", "text"}, ...]
    """
    columns = before_read.get("columns") or []
    if "ElementId" not in columns or text_column not in columns:
        raise ValueError("The before read needs the columns ElementId and %s." % text_column)
    k, t = columns.index("ElementId"), columns.index(text_column)
    c = columns.index("Category") if "Category" in columns else None
    before = {}
    for row in before_read.get("rows") or []:
        before[str(row[k])] = (row[t], row[c] if c is not None else None)
    after = {}
    for tag in after_tags or []:
        after[str(tag.get("id"))] = tag
    out = []
    for key in sorted(set(before) | set(after), key=lambda s: (len(s), s)):
        b = before.get(key)
        a = after.get(key)
        out.append({"id": key,
                    "category": (a or {}).get("category") or (b[1] if b else None),
                    "before": b[0] if b else None,
                    "after": a.get("text") if a else None})
    return out


def change_list_text(review):
    """Chat text for review_change_list()."""
    parts = ["%s %d" % (c, n) for c, n in sorted(review["by_category"].items(), key=lambda kv: -kv[1])]
    out = ["Change list by category: %s." % (", ".join(parts) or "none")]
    if review["annotations"]:
        out.append("Changed annotations (text before -> after):")
        for row in review["annotations"]:
            before, after = row.get("before"), row.get("after")
            mark = "" if before == after else "  <- TEXT CHANGES"
            if after is not None and str(after).strip() in EMPTY_TEXTS:
                mark = "  <- EMPTY AFTER"
            out.append("- %s %s: %r -> %r%s" % (row.get("category") or "", row.get("id"),
                                                 before, after, mark))
    for e in review["errors"]:
        out.append("STOP: Error in failures: %s" % e["text"])
    for s in review["stops"]:
        out.append("STOP: " + s)
    if not review["blocking"]:
        out.append("Every changed category is expected, and every changed annotation is named.")
    return "\n".join(out)

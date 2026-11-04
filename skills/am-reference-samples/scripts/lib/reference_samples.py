# -*- coding: utf-8 -*-
"""Pure logic for the am-reference-samples skill.

A reference sample view shows one sample per type. The sample is drawn
with that type. The label next to it equals the type name.

Runs under IronPython 2.7 (inside Revit) and CPython 3 (tests, CLI).
No f-strings, no type annotations, no nonlocal. No Revit imports: this
module never touches the model. The caller reads the model (through
run_query or another read path) and passes plain data in.

Data shapes (all JSON friendly):

    model_types: {"Line Styles": ["A", "B"], "Text": [...]}
        Category name -> type names in the model.
    samples: [{"category": "Line Styles", "label": "A",
               "sample_type": "A"}]
        One row per sample in the view. "label" is the text next to the
        sample. "sample_type" is the type or style the sample itself is
        drawn with. The two can differ: that is the main fault this
        skill finds.
    rename_table: {"old name": "new name"}
        Maps a label through the rename table to the current name.
    no_sample: {"Line Styles": {"<Sketch>": "reason"}}
        Category -> type name -> reason the type gets a text row
        instead of a sample. Build it with no_sample_reason().

Comparison rules: names compare exact after stripping leading and
trailing whitespace. Case matters. A sample whose sample_type equals
its label counts as present, even when the label is wrong for another
reason: mismatch and missing are separate findings.
"""

try:
    _string_types = basestring
except NameError:
    _string_types = str

# Categories and names the issue records as unable to hold a sample.
SPOT_CATEGORIES = ("Spot Elevation", "Spot Elevations",
                   "Spot Slope", "Spot Slopes")
LINE_STYLE_CATEGORY = "Line Styles"
FILL_PATTERN_CATEGORY = "Fill Patterns"
UNSETTABLE_LINE_STYLES = ("<Area Boundary>", "<Sketch>",
                          "<Invisible lines>")


def _clean(name):
    if isinstance(name, _string_types):
        return name.strip()
    return name


def check_coverage(model_types, samples):
    """Compare types in the model with samples in the view.

    Returns a dict with four findings plus a "clean" flag:

      missing: {category: [type names with no sample]}
      unknown_labels: [{index, category, label, sample_type}]
          The label names a type that is not in the model.
      duplicates: [{category, sample_type, indices, labels}]
          Two or more rows draw the same type in one category.
      mismatches: [{index, category, label, sample_type}]
          The sample itself is drawn with a type that differs from
          the label. This is the <Thin Lines> fault: the label names
          one style while the sample uses another.
      clean: True only when all four findings are empty.

    "index" is the row position in the input samples list. The fix
    plan uses it to point each operation at one row.
    """
    missing = {}
    unknown_labels = []
    mismatches = []
    by_type = {}
    for i, s in enumerate(samples):
        cat = s.get("category")
        label = _clean(s.get("label"))
        stype = _clean(s.get("sample_type"))
        names = model_types.get(cat)
        if names is None:
            unknown_labels.append({"index": i, "category": cat,
                                   "label": label, "sample_type": stype})
        else:
            clean_names = [_clean(t) for t in names]
            if label not in clean_names:
                unknown_labels.append({"index": i, "category": cat,
                                       "label": label,
                                       "sample_type": stype})
            if stype != label:
                mismatches.append({"index": i, "category": cat,
                                   "label": label, "sample_type": stype})
        key = (cat, stype)
        if key not in by_type:
            by_type[key] = []
        by_type[key].append(i)
    duplicates = []
    for key in sorted(by_type, key=lambda kv: (str(kv[0]), str(kv[1]))):
        idxs = by_type[key]
        if len(idxs) > 1:
            labels = [_clean(samples[i].get("label")) for i in idxs]
            duplicates.append({"category": key[0], "sample_type": key[1],
                               "indices": idxs, "labels": labels})
    for cat in sorted(model_types):
        sampled = set()
        for s in samples:
            if s.get("category") == cat:
                sampled.add(_clean(s.get("sample_type")))
        miss = [t for t in model_types[cat]
                if _clean(t) not in sampled]
        if miss:
            missing[cat] = miss
    clean = not (missing or unknown_labels or duplicates or mismatches)
    return {"missing": missing, "unknown_labels": unknown_labels,
            "duplicates": duplicates, "mismatches": mismatches,
            "clean": clean}


def no_sample_reason(category, type_name, has_fill_type=True,
                     is_white=False):
    """Return why a type gets a text row instead of a sample, or None.

    The caller decides "is_white" from the style appearance: white
    styles draw white, so a sample is hard to see. The caller decides
    "has_fill_type" from the model: a fill pattern with no filled
    region type gets a text row, and the fix creates no new type.
    Spot types need model geometry, so no drafting-view sample exists.
    Three built-in line styles cannot be set on a detail line.
    Any other type returns None: it can hold a sample.
    """
    cat = _clean(category)
    name = _clean(type_name)
    if cat in SPOT_CATEGORIES:
        return "needs model geometry; no drafting-view sample"
    if cat == LINE_STYLE_CATEGORY and name in UNSETTABLE_LINE_STYLES:
        return "cannot be set on a detail line"
    if cat == FILL_PATTERN_CATEGORY and not has_fill_type:
        return "no filled region type; list as text, create no new type"
    if is_white:
        return "draws white; list as text row"
    return None


def plan_fix(coverage, rename_table, model_types, no_sample, samples):
    """Build the fix plan from a coverage report. Samples first.

    "samples" is the same list check_coverage read: finding indices
    point into it. Order of application: sample_ops, then remove_ops
    and create_ops, then label_ops. A sample fix sets the sample
    type to what the label names, mapped through the rename table.
    A label fix then sets the label to the current name. The two
    steps stay separate so the sample never keeps a stale label and
    a label never names a sample that still uses the wrong type.

    Labels that name a type that does not exist land in "unfixable".
    The plan never sets such a sample to a default style.

    The plan is computed on the post-fix state, not the current
    state. A fixed row already becomes the sample its type needs, so
    no create op is emitted for that type. Rows that still draw the
    same type twice after the fixes keep one row: the first row whose
    post-fix label equals its post-fix type, else the first row.
    Removed rows lose their sample and label ops: the row is gone.

    Missing types with a no-sample reason go in "text_rows", not in
    "create_ops": the fix creates no sample for them. Missing is
    read on the post-fix state: a fix that orphans the type the
    sample used to draw earns that type a create op.

    Returns a dict with sample_ops, label_ops, create_ops,
    remove_ops, text_rows and unfixable. All op lists are empty when
    the view already matches the plan: the plan is idempotent.
    """
    sample_ops = []
    label_ops = []
    create_ops = []
    remove_ops = []
    text_rows = []
    unfixable = []
    rows = {}
    for f in coverage.get("mismatches", []):
        rows[f["index"]] = f
    for f in coverage.get("unknown_labels", []):
        rows[f["index"]] = f
    post_type = {}
    post_label = {}
    for index in sorted(rows):
        f = rows[index]
        label = f["label"]
        mapped = rename_table.get(label, label)
        names = [_clean(t) for t in model_types.get(f["category"], [])]
        if mapped in names:
            sample_ops.append({"index": index, "category": f["category"],
                               "label": label, "set_sample_to": mapped})
            label_ops.append({"index": index, "category": f["category"],
                              "set_label_to": mapped})
            post_type[index] = mapped
            post_label[index] = mapped
        else:
            unfixable.append({"index": index, "category": f["category"],
                              "label": label,
                              "reason": "label names a type that does "
                              "not exist; never set the sample to a "
                              "default style"})
            post_type[index] = f["sample_type"]
            post_label[index] = label
    for i, s in enumerate(samples):
        if i not in post_type:
            post_type[i] = _clean(s.get("sample_type"))
            post_label[i] = _clean(s.get("label"))
    grouped = {}
    for i, s in enumerate(samples):
        key = (s.get("category"), post_type[i])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(i)
    removed = set()
    for key in sorted(grouped, key=lambda kv: (str(kv[0]),
                                               str(kv[1]))):
        idxs = grouped[key]
        if len(idxs) < 2:
            continue
        keep = None
        for i in idxs:
            if post_label[i] == post_type[i]:
                keep = i
                break
        if keep is None:
            keep = idxs[0]
        for i in idxs:
            if i != keep:
                removed.add(i)
                remove_ops.append({"index": i, "category": key[0],
                                   "sample_type": key[1]})
    sample_ops = [op for op in sample_ops
                  if op["index"] not in removed]
    label_ops = [op for op in label_ops
                 if op["index"] not in removed]
    produced = {}
    for i, s in enumerate(samples):
        if i in removed:
            continue
        cat = s.get("category")
        if cat not in produced:
            produced[cat] = set()
        produced[cat].add(post_type[i])
    # Missing is computed on the post-fix state, not the report: a
    # sample fix can orphan the type the sample used to draw (the
    # fault row above stops sampling <Thin Lines>), and that type
    # needs a create op too. A type a fixed row now supplies needs
    # none.
    for cat in sorted(model_types):
        for t in model_types[cat]:
            if _clean(t) in produced.get(cat, set()):
                continue
            reason = (no_sample.get(cat, {}) or {}).get(t)
            if reason:
                text_rows.append({"category": cat, "type": t,
                                  "reason": reason})
            else:
                create_ops.append({"category": cat, "type": t})
    return {"sample_ops": sample_ops, "label_ops": label_ops,
            "create_ops": create_ops, "remove_ops": remove_ops,
            "text_rows": text_rows, "unfixable": unfixable}


def apply_plan(samples, plan):
    """Apply a fix plan to a samples list. Returns a new list.

    Removals drop rows. Sample ops set sample_type. Label ops set
    label. Create ops append a row whose label equals its type.
    Indices in the plan refer to the input list. The result feeds
    back into check_coverage: after a full plan, the only findings
    left are the text rows and unfixable labels, which are not
    samples and cannot be fixed by changing a sample.
    """
    removed = set(op["index"] for op in plan.get("remove_ops", []))
    sample_sets = {}
    for op in plan.get("sample_ops", []):
        sample_sets[op["index"]] = op["set_sample_to"]
    label_sets = {}
    for op in plan.get("label_ops", []):
        label_sets[op["index"]] = op["set_label_to"]
    out = []
    for i, s in enumerate(samples):
        if i in removed:
            continue
        row = dict(s)
        if i in sample_sets:
            row["sample_type"] = sample_sets[i]
        if i in label_sets:
            row["label"] = label_sets[i]
        out.append(row)
    for op in plan.get("create_ops", []):
        out.append({"category": op["category"], "label": op["type"],
                    "sample_type": op["type"]})
    return out


def layout_rows(header_bottom_ft, rows):
    """Place rows below an existing header. Returns top edges.

    "header_bottom_ft" is the bottom edge of the existing header row,
    in model feet. Each row gives "height_ft" (the real text box
    height, measured from the element) and "gap_ft" (the gap below
    the row above it). The first row sits one gap below the header.
    Every later row sits one gap below the row above it.

    The layout depends only on the header and the ordered rows, never
    on the current row positions. Run it twice and you get the same
    positions: that is what makes the layout script idempotent. A
    script that measures from fixed offsets, or that moves rows by a
    delta, drifts on the second run. This function cannot drift.
    """
    tops = []
    cursor = header_bottom_ft
    for row in rows:
        cursor -= row.get("gap_ft", 0.0)
        tops.append(cursor)
        cursor -= row.get("height_ft", 0.0)
    return tops


def find_overlaps(intervals):
    """Find overlapping boxes. "intervals" is [(low, high)].

    Returns [(i, j)] pairs whose intervals share a positive length.
    Boxes that only touch at an edge do not count as overlapping.
    Use it in the dry run: build one interval per row from the
    layout tops and the row heights, then fail the dry run when the
    result is not empty.
    """
    pairs = []
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            lo = intervals[i][0]
            if intervals[j][0] > lo:
                lo = intervals[j][0]
            hi = intervals[i][1]
            if intervals[j][1] < hi:
                hi = intervals[j][1]
            if hi > lo:
                pairs.append((i, j))
    return pairs


def dedupe_headers(labels):
    """Keep one header per label, in first-seen order.

    A layout script that adds a header on each run breaks this rule.
    The fix is to derive the header set from the existing headers,
    not to append one more: this function is that derivation.
    """
    seen = []
    for label in labels:
        if label not in seen:
            seen.append(label)
    return seen


def size_spread(sizes_in):
    """Describe how far sample sizes spread. Sizes are in inches.

    Returns {"min", "max", "ratio"} where ratio is max / min, or None
    when the list is empty or the smallest size is zero. The skill
    reports the spread and lets the user judge readability: the issue
    records no verified threshold at which a mixed-size view stops
    being readable, so this module sets none.
    """
    if not sizes_in:
        return {"min": None, "max": None, "ratio": None}
    mn = min(sizes_in)
    mx = max(sizes_in)
    if mn:
        ratio = mx / mn
    else:
        ratio = None
    return {"min": mn, "max": mx, "ratio": ratio}


def scale_for_print_size(model_size_ft, target_print_in):
    """Scale denominator that prints a model size at a target size.

    A scale of 1:D prints one model inch as 1/D paper inches. So D
    equals model inches divided by target paper inches. Example: a
    2 ft sample prints at 2 in when D is 12, which is 1 in = 1 ft.
    The caller picks the target size with the user; the module only
    computes the scale. A zero target raises ValueError.
    """
    if not target_print_in:
        raise ValueError("target_print_in must not be zero")
    return (model_size_ft * 12.0) / target_print_in


def snapshot_title(base_name, date_text):
    """Title for a dated snapshot table: base plus the snapshot date.

    Static tables go out of date. The date in the title tells the
    reader when the snapshot was taken. Rebuild the table by
    re-running the audit; do not edit the snapshot by hand.
    """
    return base_name + " (snapshot " + date_text + ")"

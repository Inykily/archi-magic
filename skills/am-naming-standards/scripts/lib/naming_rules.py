# -*- coding: utf-8 -*-
"""Pure naming-standards computation for the am-naming-standards skill.

Runs under IronPython 2.7 (inside Revit) and CPython 3 (tests,
naming_tables.py). No f-strings, no type annotations, no nonlocal.
No Revit imports and no file access: this module never touches the
model. It only turns a naming_inventory.py read result plus a rule
set into a rename table, a filter scan, delete flags and a
reference-view label plan.

Rule set shape (JSON, all keys optional except case/separator):

    {"case": "pascal", "separator": "_",
     "acronyms": ["TRN", "OPQ"], "allow_parens": false,
     "prefixes": {"drafting_hatch": "DR", "model_hatch": "MD"},
     "scale_style": "engineering"}

Inventory row shape (what naming_inventory.py returns):

    {"id": 123, "category": "text_type", "name": "Text 3mm",
     "keep_exact": ["Dept (A)"],
     "instance_count": 12, "referencing_type_count": 3,
     "sketch_dimension_count": 0, "in_reference_view_only": false,
     "real_size": "3mm"}

A name part that comes from other data (an area-scheme value, a
department name, a room name) goes in keep_exact. The transform
keeps it byte for byte. A script cannot tell an acronym from a
word in all-caps text, so an all-caps word that is not a known
acronym is FLAGGED, never guessed.
"""

import re

# Acronyms the office spells in capitals. TRN = transparent (Masking
# off), OPQ = opaque (Masking on). The user extends this list.
DEFAULT_ACRONYMS = ("TRN", "OPQ")

# How to rename one category. Line styles are the trap from the
# issue: Category.Name and the GraphicsStyle name are read-only.
# The name that works is the subcategory element name.
NAME_PATHS = {
    "view_template": "type element Name",
    "text_type": "type element Name",
    "dimension_type": "type element Name",
    "line_style": "subcategory element: doc.GetElement(subcategory.Id).Name "
                  "(Category.Name and the GraphicsStyle name are read-only)",
    "family_type": "family symbol Name",
    "filled_region_type": "type element Name",
    "fill_pattern": "pattern element Name",
}

_WORD_SPLIT = re.compile(r"[_\-\s]+")
_SIZE_TOKEN = re.compile(r"(\d+(?:\.\d+)?\s*(?:mm|cm|m|in|\"|'))")
_TRAILING_NUMBER = re.compile(r"\s\d+$")


def default_rules():
    """One rule set with the office defaults from the issue."""
    return {"case": "pascal", "separator": "_",
            "acronyms": list(DEFAULT_ACRONYMS),
            "allow_parens": False, "prefixes": {},
            "scale_style": "engineering"}


def _pascal_word(word, acronyms):
    """Capitalize one word. Returns (word, flag or None)."""
    if not word:
        return word, None
    upper = word.upper()
    if upper in acronyms:
        return upper, None
    if word == upper and len(word) > 1:
        # All-caps and not a known acronym: could be an acronym or a
        # word. Do not guess. Flag it and title-case it for preview.
        return word.capitalize(), "unknown_acronym"
    return word.capitalize(), None


def transform_name(name, rules, keep_exact=None):
    """Apply the global rules to one name.

    Returns (new_name, flags). keep_exact parts are kept byte for
    byte and restored after the transform. A kept part that holds
    "( )" while the rules forbid parens adds the
    "data_part_has_parens" flag: the rename is not done until the
    user decides about that part.
    """
    flags = []
    separator = rules.get("separator", "_")
    acronyms = set(rules.get("acronyms", list(DEFAULT_ACRONYMS)))
    kept = keep_exact or []
    work = name
    slots = {}
    for i, part in enumerate(kept):
        slot = "\x00%d\x00" % i
        if part and part in work:
            work = work.replace(part, slot, 1)
            slots[slot] = part
            if not rules.get("allow_parens", False):
                if "(" in part or ")" in part:
                    flags.append("data_part_has_parens")
    words = [w for w in _WORD_SPLIT.split(work) if w]
    out = []
    for word in words:
        if word in slots:
            out.append(slots[word])
            flags.append("data_part_kept")
            continue
        new_word, flag = _pascal_word(word, acronyms)
        out.append(new_word)
        if flag and flag not in flags:
            flags.append(flag)
    return separator.join(out), flags


def validate_name(name, rules):
    """Flag rule breaks in one name. Empty list means clean."""
    flags = []
    if "[" in name or "]" in name:
        flags.append("has_brackets")
    if not rules.get("allow_parens", False):
        if "(" in name or ")" in name:
            flags.append("has_parens")
    if "  " in name:
        flags.append("double_space")
    separator = rules.get("separator", "_")
    if separator + separator in name:
        flags.append("double_separator")
    if name.startswith(separator) or name.endswith(separator):
        flags.append("edge_separator")
    if _TRAILING_NUMBER.search(name):
        flags.append("trailing_space_number")
    return flags


def parse_scale_token(token):
    """Read one scale token. Returns (style, normalized, error).

    Architects read "1-30" (engineering) and "1-32in"
    (architectural). "1in=30ft" is rejected: it reads wrong.
    """
    if "=" in token:
        return None, None, "use 1-30 or 1-32in, not 1in=30ft"
    m = re.match(r"^1-(\d+)in$", token)
    if m:
        return "architectural", token, None
    m = re.match(r"^1-(\d+)$", token)
    if m:
        return "engineering", token, None
    return None, None, "not a scale token (want 1-30 or 1-32in)"


def size_mismatch(name, real_size):
    """True when a size in the name differs from the real property.

    real_size is the value from the model (for example "3mm").
    No size in the name means no check, not a pass.
    """
    if not real_size:
        return False
    m = _SIZE_TOKEN.search(name)
    if not m:
        return False
    named = re.sub(r"\s+", "", m.group(1))
    real = re.sub(r"\s+", "", real_size)
    return named.lower() != real.lower()


def usage_for_display(row):
    """Usage counts for one inventory row, sketch dims left out.

    Returns (count, note). The count is the referencing-type
    count when present, else the instance count. Internal sketch
    dimensions never count: they inflate dimension-style counts
    (about 229,000 in the issue) and mean nothing.
    """
    sketch = row.get("sketch_dimension_count", 0)
    if row.get("referencing_type_count") is not None:
        count = row["referencing_type_count"]
    else:
        count = row.get("instance_count", 0) - sketch
    if row.get("in_reference_view_only"):
        return count, "used only in the reference view"
    if sketch:
        return count, "sketch dimensions excluded"
    return count, ""


def build_rename_table(rows, rules):
    """Build the rename table the user approves before any rename.

    Each row: id, category, old, new, flags, name_path. A row
    whose new name equals its old name is marked "unchanged".
    """
    table = []
    for row in rows:
        new_name, flags = transform_name(
            row["name"], rules, row.get("keep_exact"))
        flags = flags + validate_name(new_name, rules)
        if row.get("real_size") and size_mismatch(row["name"],
                                                 row["real_size"]):
            flags.append("size_in_name_mismatch")
        if new_name == row["name"]:
            flags.append("unchanged")
        count, note = usage_for_display(row)
        table.append({"id": row["id"], "category": row["category"],
                      "old": row["name"], "new": new_name,
                      "flags": sorted(set(flags)),
                      "name_path": NAME_PATHS.get(row["category"],
                                                  "type element Name"),
                      "usage_count": count, "usage_note": note})
    return table


def scan_filter_refs(filters, old_names):
    """Find view and schedule filters that use an old type name.

    filters: [{id, name, kind, values: [str]}]. kind is
    "view_filter" or "schedule_filter". A hit lists that filter
    in the rename preview, so no filter silently keeps matching
    a name that no longer exists. Matching is case-insensitive
    substring on the rule values.
    """
    hits = []
    lowered = [(n, n.lower()) for n in old_names]
    for f in filters:
        for value in f.get("values", []):
            low_value = value.lower()
            for old, low_old in lowered:
                if low_old and low_old in low_value:
                    hits.append({"filter_id": f["id"],
                                 "filter_name": f["name"],
                                 "filter_kind": f.get("kind", "view_filter"),
                                 "old_name": old,
                                 "matched_value": value})
    return hits


def check_delete(row, unplaced_group_types, placed_group_members):
    """Flag a type delete that is unsafe, before the dry run.

    unplaced_group_types: [{id, name}] with no placed instance.
    Their members cannot be listed from the type alone, so while
    any exist every delete candidate is flagged
    "unplaced_groups_exist": the hidden-member case from the
    issue cannot be ruled out. placed_group_members:
    {group_id: [member_type_ids]} from placed instances. A row
    id in a member list is flagged "used_by_group_member".
    """
    flags = []
    if unplaced_group_types:
        flags.append("unplaced_groups_exist")
    for group_id, members in placed_group_members.items():
        if row["id"] in members:
            flags.append("used_by_group_member")
    if row.get("instance_count", 0) > 0:
        flags.append("has_instances")
    return flags


def compare_dry_run(expected_ids, dry_run_ids):
    """Compare a dry-run deleted list with the expected list.

    Returns (unexpected, missing): ids the dry run would delete
    that were not expected, and expected ids it would not delete.
    """
    expected = set(expected_ids)
    dry = set(dry_run_ids)
    return sorted(dry - expected), sorted(expected - dry)


def plan_reference_labels(views, rename_map):
    """Plan label updates in reference and legend views.

    views: [{id, name, kind, labels: [{text, sample_style_exists,
    starts_with_type_name, has_labels}]}]. kind is
    "reference" or "legend". The pairing differs per view, so
    each label gets its own action: update_text, check_sample
    (a sample line whose style does not exist), no_labels (a
    dimension example group with no labels), or manual_check.
    """
    plan = []
    for view in views:
        for label in view.get("labels", []):
            text = label.get("text", "")
            new_text = rename_map.get(text, text)
            if not label.get("has_labels", True):
                action = "no_labels"
            elif not label.get("sample_style_exists", True):
                action = "check_sample"
            elif new_text != text:
                action = "update_text"
            else:
                action = "manual_check"
            plan.append({"view_id": view["id"],
                         "view_name": view["name"],
                         "view_kind": view.get("kind", "reference"),
                         "old_label": text, "new_label": new_text,
                         "action": action})
    return plan

# -*- coding: utf-8 -*-
"""Pure material-color computation for the am-safe-change skill.

Recipe material-colors (issue #27): read the current Shading and Surface
Pattern colors of materials, let the user tune them in a panel, then
write them back through the normal read, preview, dry run, commit flow.

Runs under CPython 3 and IronPython 2.7: no f-strings, no type
annotations, no nonlocal. No Revit imports: this module never touches
the model. It only turns a read result and a panel request into a
change preview, and it checks WCAG contrast ratios for the palette
helper.

Material dict shape (what read_materials.py returns):
    {"id": 123, "name": "Floor - Timber", "shading": [210, 180, 140],
     "surface_pattern_id": 456, "surface_pattern_name": "Diagonal",
     "surface_pattern_color": [90, 90, 90],
     "used_by_categories": ["Floors", "Walls"], "used_by_truncated": False}
"shading" is the material Color (None when the material has none).
"surface_pattern_color" is the Surface Foreground Pattern color (None
when the material has no surface pattern, or the color is not set).
"used_by_categories" lists the categories of elements that use the
material; it feeds the preview's expected_dependent_categories.

Panel request shape (what the panel copies for Revit):
    {"kind": "material-colors", "source": "am-safe-change",
     "items": [{"id": 123, "shading": [200, 170, 130],
                "surface_pattern_color": [80, 80, 80]}]}
Only rows the user changed are in "items". "surface_pattern_color"
may be left out to keep the current pattern color.
"""
import re

COLUMNS = ["ElementId", "Material", "Shading", "Surface pattern"]
CHANGED = ["Shading", "Surface pattern"]

# WCAG 2.1: normal text needs 4.5:1 against its background (AA).
TEXT_CONTRAST_MIN = 4.5
# A pattern line needs 3:1 against its background to stay visible.
PATTERN_CONTRAST_MIN = 3.0


def rgb_to_hex(rgb):
    """[210, 180, 140] -> "#D2B48C"."""
    return "#%02X%02X%02X" % (rgb[0], rgb[1], rgb[2])


def rgb_text(rgb):
    """[210, 180, 140] -> "rgb(210, 180, 140)"."""
    if rgb is None:
        return "-"
    return "rgb(%d, %d, %d)" % (rgb[0], rgb[1], rgb[2])


def _linear(c):
    """One sRGB channel (0-255) to linear light (0-1)."""
    v = c / 255.0
    if v <= 0.03928:
        return v / 12.92
    return ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    """WCAG relative luminance of an RGB color (0-1)."""
    return (0.2126 * _linear(rgb[0]) + 0.7152 * _linear(rgb[1])
            + 0.0722 * _linear(rgb[2]))


def contrast_ratio(a, b):
    """WCAG contrast ratio between two RGB colors (1.0-21.0)."""
    la = relative_luminance(a)
    lb = relative_luminance(b)
    hi, lo = (la, lb) if la >= lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def suggest_greys(count, foreground=None):
    """N light greys that stay readable (issue #27 palette helper).

    count      : how many greys to return (1 or more).
    foreground : the pattern foreground RGB the greys must show (default
                 black). Each grey states its WCAG ratio against black
                 text and against the foreground.

    The greys run from white down to the darkest grey whose contrast
    with black text is still 4.5:1 (WCAG AA for normal text), evenly
    spaced. A grey darker than that would make black text fail AA.
    """
    if count is None or count < 1:
        raise ValueError("Palette needs at least 1 grey.")
    fg = list(foreground) if foreground else [0, 0, 0]
    darkest = 0
    for g in range(255, -1, -1):
        if contrast_ratio([g, g, g], [0, 0, 0]) >= TEXT_CONTRAST_MIN:
            darkest = g
        else:
            break
    if count == 1:
        levels = [255]
    else:
        step = (255 - darkest) / float(count - 1)
        levels = [int(round(255 - step * i)) for i in range(count)]
    out = []
    for g in levels:
        rgb = [g, g, g]
        out.append({"rgb": rgb, "hex": rgb_to_hex(rgb),
                    "text_contrast": round(contrast_ratio(rgb, [0, 0, 0]), 2),
                    "pattern_contrast": round(contrast_ratio(rgb, fg), 2)})
    return out


def palette_table(greys, foreground=None):
    """Compact text of a suggested palette, for chat."""
    fg = rgb_text(foreground) if foreground else "rgb(0, 0, 0)"
    out = ["Suggested light greys (pattern foreground %s):" % fg]
    for g in greys:
        out.append("- %s %s: text %.2f:1, pattern %.2f:1."
                   % (g["hex"], rgb_text(g["rgb"]), g["text_contrast"],
                      g["pattern_contrast"]))
    return "\n".join(out)


_ESC_RE = None


def unescape(text):
    """Reverse the IronPython ASCII escaping done by read_materials.py."""
    global _ESC_RE
    if _ESC_RE is None:
        _ESC_RE = re.compile(r"\\(\\|u[0-9a-fA-F]{4})")

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
    """Turn a read_materials.py result (or the full run JSON) into material dicts."""
    if "result" in result and "materials" not in result:
        result = result["result"]
    mats = []
    for m in result["materials"]:
        d = dict(m)
        if result.get("escaped"):
            d["name"] = unescape(d["name"])
            if d.get("surface_pattern_name"):
                d["surface_pattern_name"] = unescape(d["surface_pattern_name"])
        mats.append(d)
    return mats


def _is_rgb(value):
    """True when value is [r, g, b] with each part an int 0-255."""
    if not isinstance(value, list) or len(value) != 3:
        return False
    for part in value:
        if not isinstance(part, int) or isinstance(part, bool):
            return False
        if part < 0 or part > 255:
            return False
    return True


def validate_request(request, materials):
    """Check a panel request against the read result.

    Returns (items, errors). items are the changed rows with their new
    colors; errors is a list of plain-text problems. An item with no
    change against the current colors is an error, not a silent skip.
    """
    errors = []
    if not isinstance(request, dict) or request.get("kind") != "material-colors":
        return [], ["Request kind must be 'material-colors' (the panel copies it)."]
    by_id = dict((m["id"], m) for m in materials)
    raw = request.get("items")
    if not isinstance(raw, list) or not raw:
        return [], ["The request has no changed rows. Change a color in the panel first."]
    items = []
    seen = set()
    for it in raw:
        if not isinstance(it, dict) or "id" not in it:
            errors.append("A row has no material id.")
            continue
        eid = it["id"]
        if eid in seen:
            errors.append("Material %s is listed twice." % eid)
            continue
        seen.add(eid)
        mat = by_id.get(eid)
        if mat is None:
            errors.append("Material %s is not in the model (deleted, or a different model)." % eid)
            continue
        shading = it.get("shading")
        pattern = it.get("surface_pattern_color")
        if shading is not None and not _is_rgb(shading):
            errors.append("Material %s shading is not an RGB list (0-255): %r." % (eid, shading))
            continue
        if pattern is not None and not _is_rgb(pattern):
            errors.append("Material %s pattern color is not an RGB list (0-255): %r." % (eid, pattern))
            continue
        if shading is None and pattern is None:
            errors.append("Material %s '%s' changes nothing." % (eid, mat.get("name") or ""))
            continue
        if shading is not None and shading == list(mat.get("shading") or []):
            shading = None
        if pattern is not None and pattern == list(mat.get("surface_pattern_color") or []):
            pattern = None
        if shading is None and pattern is None:
            errors.append("Material %s '%s' changes nothing (new colors equal the current ones)."
                          % (eid, mat.get("name") or ""))
            continue
        items.append({"id": eid, "shading": shading,
                      "surface_pattern_color": pattern})
    return items, errors


def compute_preview(request, materials, title=None):
    """Build the change-preview (shared contract) for a validated request."""
    items, errors = validate_request(request, materials)
    if errors:
        raise ValueError("Request rejected: " + " ".join(errors))
    by_id = dict((m["id"], m) for m in materials)
    before, after, steps = [], [], []
    # Categories of elements that use the changed materials redraw.
    # Keynote Tags and Legends also redraw: tags point at elements that
    # use the material, and legend components show them (issue #28: a
    # 10-material change regenerated 831 keynote tags and legend parts).
    expected = set(["Keynote Tags", "Legends"])
    warnings = []
    for it in items:
        mat = by_id[it["id"]]
        name = mat.get("name") or ""
        old_shading = mat.get("shading")
        old_pattern = mat.get("surface_pattern_color")
        new_shading = it["shading"] if it["shading"] is not None else old_shading
        new_pattern = (it["surface_pattern_color"]
                       if it["surface_pattern_color"] is not None else old_pattern)
        before.append([it["id"], name, rgb_text(old_shading), rgb_text(old_pattern)])
        after.append([it["id"], name, rgb_text(new_shading), rgb_text(new_pattern)])
        for cat in mat.get("used_by_categories") or []:
            expected.add(cat)
        if new_pattern is not None and new_shading is not None:
            ratio = contrast_ratio(new_pattern, new_shading)
            if ratio < PATTERN_CONTRAST_MIN:
                warnings.append({"row": str(it["id"]), "type": "low_pattern_contrast",
                                 "blocking": False,
                                 "text": "Pattern color on '%s' is hard to see on the new shading (contrast %.2f:1, needs %.1f:1)."
                                         % (name, ratio, PATTERN_CONTRAST_MIN)})
        steps.append({"id": it["id"],
                      "shading": it["shading"],
                      "surface_pattern_color": it["surface_pattern_color"],
                      "expect": {"shading": list(old_shading) if old_shading else None,
                                 "surface_pattern_color": list(old_pattern) if old_pattern else None},
                      "expectAfter": {"shading": list(new_shading) if new_shading else None,
                                      "surface_pattern_color": list(new_pattern) if new_pattern else None}})
    truncated = any(m.get("used_by_truncated") for m in materials)
    notes = ["%d of %d materials change." % (len(items), len(materials)),
             "Shading is the color Revit shows in shaded views. "
             "Surface pattern is the fill pattern color.",
             "Expected dependents (they redraw): %s."
             % (", ".join(sorted(expected)) if expected else "none found")]
    if truncated:
        notes.append("The used-by scan stopped at its cap, so the expected "
                     "dependents list may miss categories.")
    return {"kind": "change-preview",
            "title": title or ("Change colors of %d material(s)" % len(items)),
            "keyColumn": "ElementId",
            "columns": list(COLUMNS),
            "changedColumns": list(CHANGED),
            "before": before,
            "after": after,
            "notes": notes,
            "warnings": warnings,
            "blocked": False,
            "params": {"source": request.get("source") or ""},
            "steps": steps,
            "expected_dependent_categories": sorted(expected)}


def text_table(preview):
    """Compact markdown table for chat."""
    out = ["| ElementId | Material | Shading before -> after | Surface pattern before -> after |",
           "|---|---|---|---|"]
    for b, a in zip(preview["before"], preview["after"]):
        out.append("| %s | %s | %s -> %s | %s -> %s |" % (b[0], b[1], b[2], a[2], b[3], a[3]))
    out.append("")
    out.append("Changed: %d. Warnings: %d." % (len(preview["steps"]), len(preview["warnings"])))
    for w in preview["warnings"]:
        out.append("- %s[%s] %s" % ("BLOCKING " if w.get("blocking") else "", w["type"], w["text"]))
    for n in preview["notes"]:
        out.append("- " + n)
    return "\n".join(out)


def actual_from(data):
    """{id: {"shading", "surface_pattern_color"}} from an apply or read result."""
    if "result" in data and "materials" not in data and "rows" not in data:
        data = data["result"]
    if data is None:
        raise ValueError("The run has no result (check status and error).")
    if "rows" in data:
        out = {}
        for r in data["rows"]:
            out[r["id"]] = {"shading": r.get("shading"),
                            "surface_pattern_color": r.get("surface_pattern_color")}
        return out
    if "materials" not in data:
        raise ValueError("The run has no rows or materials (check status and error).")
    mats = load_read_result(data)
    return dict((m["id"], {"shading": m.get("shading"),
                           "surface_pattern_color": m.get("surface_pattern_color")})
                for m in mats)


def compare(preview, actual):
    """Compare preview steps' expectAfter with actual results.

    actual: {id: {"shading", "surface_pattern_color"}} for every changed
    material. Returns a list of difference strings. Empty = matches.
    """
    diffs = []
    for st in preview.get("steps") or []:
        eid = st["id"]
        got = actual.get(eid)
        want = st["expectAfter"]
        if got is None:
            diffs.append("material %s: missing in actual result" % eid)
            continue
        for key in ("shading", "surface_pattern_color"):
            w = want.get(key)
            g = got.get(key)
            if (w is None) != (g is None) or (w is not None and list(w) != list(g or [])):
                diffs.append("material %s: %s expected %s, got %s"
                             % (eid, key, rgb_text(w), rgb_text(g)))
    want_ids = set(st["id"] for st in preview.get("steps") or [])
    for eid in sorted(actual):
        if eid not in want_ids:
            diffs.append("material %s: changed but not in preview" % eid)
    return diffs

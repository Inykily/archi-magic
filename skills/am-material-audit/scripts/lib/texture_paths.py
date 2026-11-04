# -*- coding: utf-8 -*-
"""Pure texture-path computation for the am-material-audit skill.

Runs under IronPython 2.7 (inside Revit) and CPython 3 (tests,
texture_report.py). No f-strings, no type annotations, no nonlocal.
No Revit imports: this module never touches the model. It only turns a
read_texture_paths.py read result into a classified audit.

Read-result material shape (what read_texture_paths.py returns):
    {"id": 123, "name": "Floor Finish - Oak", "asset_id": 456,
     "asset_name": "Oak", "asset_unreadable": False,
     "slots": [{"slot": "generic_diffuse", "path": "C:\\tex\\oak.jpg"}]}

Statuses, one per slot:
    "ok"                    a stored candidate file exists.
    "ok_in_autodesk_library" no stored candidate exists, but the file
                            name resolves in the installed Autodesk
                            library. Revit finds a library texture by
                            file name alone, and the library lives under
                            either Program Files folder, so a stored
                            path under the other folder still counts.
    "file_not_found"        no candidate exists and the name is not in
                            the library.
    "empty_path"            the stored path is empty.
    "asset_unreadable"      the material has no readable rendering asset
                            (no row per slot; listed separately).

Stored paths have several forms: an absolute local path, a UNC or mapped
drive path, a bare file name, a "|" separated list of candidates, and
mixed "/" and "\\" separators. Testing only os.path.isfile(path) gives
wrong answers, so classification splits on "|", normalizes the
separators, tests every candidate, then falls back to the library
by file name.
"""
import re

_ESC_RE = re.compile(r"\\(\\|u[0-9a-fA-F]{4})")

# What the texture audit does NOT cover. The read script reports its own
# notes too; the default here covers hand-made read results (tests).
NOTES_DEFAULT = [
    "Paths are returned raw. Classification happens in texture_paths.py.",
    "Bare file names are resolved only against the installed Autodesk "
    "library, not against Revit's Additional render appearance paths option.",
]


def unescape(text):
    """Reverse the IronPython ASCII escaping done by read_texture_paths.py."""
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
    """Turn a read_texture_paths.py result (or the full run JSON) into data.

    Returns (materials, result). The result is unwrapped from the run JSON
    when needed, and names are unescaped when the result says "escaped".
    """
    if "result" in result and "materials" not in result:
        result = result["result"]
    materials = []
    for m in result["materials"]:
        d = dict(m)
        if result.get("escaped"):
            d["name"] = unescape(d["name"])
            d["asset_name"] = unescape(d.get("asset_name") or "")
        materials.append(d)
    return materials, result


def split_candidates(raw):
    """A stored path string -> its "|" separated candidates, stripped.

    None and "" give []. Empty candidates inside the list are dropped:
    "a.jpg||b.jpg" means a.jpg and b.jpg, not a third empty path.
    """
    if raw is None:
        return []
    parts = []
    for piece in str(raw).split("|"):
        piece = piece.strip()
        if piece:
            parts.append(piece)
    return parts


def normalize_path(path):
    """One candidate -> its normalized form: "/" becomes "\\", stripped."""
    return str(path).strip().replace("/", "\\")


def basename_of(path):
    """File name of a normalized path. "C:\\tex\\oak.jpg" -> "oak.jpg"."""
    path = normalize_path(path)
    if "\\" in path:
        return path.rsplit("\\", 1)[-1]
    return path


def classify_path(raw, exists, library_names):
    """Status of one stored path string.

    exists         : callable, normalized candidate -> bool. On Windows
                     this is os.path.isfile; tests pass a fake set.
    library_names  : set of lower-cased file names in the installed
                     Autodesk library (both Program Files folders).
    """
    candidates = split_candidates(raw)
    if not candidates:
        return "empty_path"
    normalized = [normalize_path(c) for c in candidates]
    for candidate in normalized:
        if exists(candidate):
            return "ok"
    for candidate in normalized:
        if basename_of(candidate).lower() in library_names:
            return "ok_in_autodesk_library"
    return "file_not_found"


def audit_texture_paths(read_result, exists, library_names):
    """Build the texture audit from a read_texture_paths.py read result.

    Returns {"prefix","model","revit_year","timestamp","rows",
    "unreadable","counts","notes"}. Each row has "material_id",
    "material_name", "asset_id", "asset_name", "materials_on_asset"
    (how many materials share the asset, so one asset edit is counted
    for every material it fixes), "slot", "path" (the raw stored string),
    "candidates" (normalized), and "status".
    """
    materials, result = load_read_result(read_result)
    library_names = set(n.lower() for n in (library_names or []))
    by_asset = {}
    for m in materials:
        by_asset.setdefault(m.get("asset_id"), []).append(m)
    rows = []
    unreadable = []
    for m in materials:
        if m.get("asset_unreadable"):
            unreadable.append({"material_id": m["id"],
                               "material_name": m["name"],
                               "asset_id": m.get("asset_id"),
                               "asset_name": m.get("asset_name") or ""})
            continue
        shared = len(by_asset.get(m.get("asset_id")) or [m])
        for slot in m.get("slots") or []:
            raw = slot.get("path")
            rows.append({
                "material_id": m["id"],
                "material_name": m["name"],
                "asset_id": m.get("asset_id"),
                "asset_name": m.get("asset_name") or "",
                "materials_on_asset": shared,
                "slot": slot.get("slot") or "",
                "path": raw,
                "candidates": [normalize_path(c)
                               for c in split_candidates(raw)],
                "status": classify_path(raw, exists, library_names),
            })
    counts = {"materials": len(materials),
              "slots": len(rows),
              "unreadable_assets": len(unreadable)}
    for status in ("ok", "ok_in_autodesk_library", "file_not_found",
                   "empty_path"):
        counts[status] = len([r for r in rows if r["status"] == status])
    return {
        "prefix": result.get("prefix", ""),
        "model": result.get("model", ""),
        "revit_year": result.get("revit_year", ""),
        "timestamp": result.get("timestamp", ""),
        "rows": rows,
        "unreadable": unreadable,
        "counts": counts,
        "notes": list(result.get("notes") or NOTES_DEFAULT),
    }


def _cell(text, width):
    """Pad or cut a table cell to width. Text is ASCII or short on purpose."""
    text = "" if text is None else str(text)
    if len(text) > width:
        text = text[:width - 1] + "~"
    return text + " " * (width - len(text))


def render_table(audit_result):
    """Plain-text texture audit table plus summary, for chat and terminal."""
    rows = audit_result["rows"]
    counts = audit_result["counts"]
    lines = []
    lines.append("Texture image paths: %d materials, %d slots, %d ok, "
                 "%d ok in Autodesk library, %d missing, %d empty, "
                 "%d unreadable assets"
                 % (counts["materials"], counts["slots"], counts["ok"],
                    counts["ok_in_autodesk_library"], counts["file_not_found"],
                    counts["empty_path"], counts["unreadable_assets"]))
    if rows:
        widths = (24, 20, 16, 44, 22)
        header = [_cell(t, w) for t, w in zip(
            ["Material", "Asset", "Slot", "Stored path", "Status"], widths)]
        lines.append(" | ".join(header))
        lines.append("-+-".join(["-" * w for w in widths]))
        for r in rows:
            shared = ""
            if r["materials_on_asset"] > 1:
                shared = " (shared by %d materials)" % r["materials_on_asset"]
            cells = [_cell(r["material_name"], widths[0]),
                     _cell(r["asset_name"] + shared, widths[1]),
                     _cell(r["slot"], widths[2]),
                     _cell(r["path"], widths[3]),
                     _cell(r["status"], widths[4])]
            lines.append(" | ".join(cells))
    if audit_result["unreadable"]:
        lines.append("")
        lines.append("Unreadable assets (no rendering asset to read):")
        for u in audit_result["unreadable"]:
            lines.append("  %s (asset %s)" % (u["material_name"],
                                              u["asset_id"]))
    missing = [r for r in rows if r["status"] == "file_not_found"]
    if missing:
        lines.append("")
        lines.append("Missing files:")
        for r in missing:
            lines.append("  %s / %s: %s" % (r["material_name"], r["slot"],
                                            r["path"]))
    lines.append("")
    lines.append("Notes: %s" % "; ".join(audit_result["notes"]))
    return "\n".join(lines)

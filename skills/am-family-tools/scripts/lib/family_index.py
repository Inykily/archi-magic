# -*- coding: utf-8 -*-
"""Index a local family library folder and search it, without Revit.

build_index() walks one folder, reads each .rfa file's own metadata
(rfa_metadata.read_family_file) and its type catalog (.txt with the same
name), and returns one JSON-ready index. search() filters that index by
text, category, type name and parameter value. mark_in_model() adds the
"already in the open model" columns from a read_loaded_families.py result.

Safety:
- Read only. The library files are never changed.
- Links, junctions and loops are not followed.
- Cloud-only files (OneDrive, Autodesk Desktop Connector placeholders) are
  skipped without opening, so a scan never starts a download.
- Bounded: number of entries, folder depth and families.

Pure Python. Runs in CPython 3 on the user's computer; the syntax stays
IronPython 2.7 compatible (no f-strings, no keyword-only arguments).
"""
import hashlib
import io
import json
import os
import re
import time

import rfa_metadata

INDEX_KIND = "family-library-index"
INDEX_VERSION = 1
MAX_ENTRIES = 50000
MAX_DEPTH = 16
MAX_FAMILIES = 5000
MAX_RESULTS = 500

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY = (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN
              | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)

BACKUP = re.compile(r"\.\d{4}\.rfa\Z", re.IGNORECASE)
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")


def fold(text):
    """Case- and space-insensitive form for matching."""
    return u" ".join((text or u"").split()).casefold() if hasattr(u"", "casefold") \
        else u" ".join((text or u"").split()).lower()


def _attributes(info):
    return getattr(info, "st_file_attributes", 0) or 0


def _is_link(entry):
    if entry.is_symlink():
        return True
    is_junction = getattr(entry, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    return False


def _stamp(info):
    return {"size": int(info.st_size), "mtime_ns": int(getattr(info, "st_mtime_ns", info.st_mtime * 1e9))}


def _thumbnail_name(relative, stamp):
    key = u"%s|%d|%d" % (relative, stamp["size"], stamp["mtime_ns"])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".png"


def walk_library(root, max_entries=MAX_ENTRIES, max_depth=MAX_DEPTH):
    """Find .rfa files and their catalogs under root.

    Returns (families, skipped, limits_hit) where families is a list of
    dicts {"relative", "path", "info", "catalog_path", "catalog_info"} and
    skipped is a list of {"relative", "reason"}.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise ValueError("The library folder does not exist or is not a folder.")
    families = []
    skipped = []
    limits = []
    seen_dirs = set()
    count = 0
    stopped = False
    stack = [(root, u"", 0)]
    while stack and not stopped:
        folder, relative, depth = stack.pop()
        try:
            info = os.stat(folder)
            key = (info.st_dev, info.st_ino)
            if info.st_ino and key in seen_dirs:
                skipped.append({"relative": relative or u".", "reason": "loop"})
                continue
            seen_dirs.add(key)
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            skipped.append({"relative": relative or u".", "reason": "unreadable_folder"})
            continue
        by_lower = {}
        for entry in entries:
            by_lower.setdefault(entry.name.lower(), []).append(entry)
        subfolders = []
        for entry in entries:
            count += 1
            if count > max_entries:
                limits.append("entries")
                stopped = True
                break
            child = relative + u"/" + entry.name if relative else entry.name
            try:
                if _is_link(entry):
                    skipped.append({"relative": child, "reason": "link_not_followed"})
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 > max_depth:
                        if "depth" not in limits:
                            limits.append("depth")
                        skipped.append({"relative": child, "reason": "too_deep"})
                    else:
                        subfolders.append((entry.path, child, depth + 1))
                    continue
                if not entry.name.lower().endswith(".rfa"):
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                skipped.append({"relative": child, "reason": "unreadable_file"})
                continue
            if _attributes(info) & CLOUD_ONLY:
                skipped.append({"relative": child, "reason": "cloud_only"})
                continue
            if len(families) >= MAX_FAMILIES:
                if "families" not in limits:
                    limits.append("families")
                skipped.append({"relative": child, "reason": "family_limit"})
                continue
            catalog = by_lower.get(entry.name[:-4].lower() + ".txt")
            record = {"relative": child, "path": entry.path, "info": info,
                      "catalog_path": None, "catalog_info": None}
            if catalog:
                cat = catalog[0]
                try:
                    cat_info = cat.stat(follow_symlinks=False)
                    if _is_link(cat):
                        skipped.append({"relative": child[:-4] + ".txt", "reason": "link_not_followed"})
                    elif _attributes(cat_info) & CLOUD_ONLY:
                        skipped.append({"relative": child[:-4] + ".txt", "reason": "cloud_only"})
                    else:
                        record["catalog_path"] = cat.path
                        record["catalog_info"] = cat_info
                except OSError:
                    skipped.append({"relative": child[:-4] + ".txt", "reason": "unreadable_file"})
            families.append(record)
        for item in reversed(subfolders):
            stack.append(item)
    families.sort(key=lambda r: r["relative"].lower())
    return families, skipped, limits


def _read_catalog(path):
    with io.open(path, "rb") as f:
        data = f.read(rfa_metadata.MAX_CATALOG_BYTES + 1)
    return rfa_metadata.parse_type_catalog(data)


def build_index(root, thumbnails_dir=None, previous=None, max_entries=MAX_ENTRIES,
                max_depth=MAX_DEPTH, now=None):
    """Build the index dict for one library folder.

    thumbnails_dir: folder for PNG thumbnails (created if missing), or None.
    previous: an earlier index dict for the same root. A family whose file
    and catalog size and time are unchanged reuses its earlier row.
    """
    root = os.path.abspath(root)
    families, skipped, limits = walk_library(root, max_entries, max_depth)
    reuse = {}
    if previous and previous.get("kind") == INDEX_KIND and previous.get("root") == root:
        for row in previous.get("families", []):
            reuse[row["relative"]] = row
    if thumbnails_dir:
        thumbnails_dir = os.path.abspath(thumbnails_dir)
        if not os.path.isdir(thumbnails_dir):
            os.makedirs(thumbnails_dir)
    rows = []
    reused = 0
    names = {}
    for record in families:
        stamp = _stamp(record["info"])
        catalog_stamp = _stamp(record["catalog_info"]) if record["catalog_info"] is not None else None
        old = reuse.get(record["relative"])
        if (old is not None and old.get("stamp") == stamp and old.get("catalog_stamp") == catalog_stamp
                and (not thumbnails_dir or old.get("thumbnail") is None
                     or os.path.isfile(os.path.join(thumbnails_dir, old["thumbnail"])))
                and (not thumbnails_dir or old.get("thumbnail_checked"))):
            row = dict(old)
            reused += 1
        else:
            meta = rfa_metadata.read_family_file(record["path"], want_thumbnail=bool(thumbnails_dir))
            name = os.path.basename(record["relative"])[:-4]
            folder = os.path.dirname(record["relative"])
            row = {
                "relative": record["relative"],
                "family": name,
                "folder": folder,
                "stamp": stamp,
                "catalog_stamp": catalog_stamp,
                "backup": bool(BACKUP.search(record["relative"])),
                "status": meta["status"],
                "reason": meta["reason"],
                "category": meta["category"],
                "omniclass": meta["omniclass"],
                "revit_version": meta["revit_version"],
                "types": [dict(t, origin="embedded") for t in meta["types"]],
                "types_truncated": meta["types_truncated"],
                "catalog": None,
                "thumbnail": None,
                "thumbnail_checked": bool(thumbnails_dir),
            }
            if record["catalog_path"]:
                catalog = _read_catalog(record["catalog_path"])
                row["catalog"] = {"relative": record["relative"][:-4] + ".txt",
                                  "issues": catalog["issues"],
                                  "type_count": len(catalog["types"])}
                row["types"].extend(dict(t, origin="catalog") for t in catalog["types"])
            image = meta.get("thumbnail")
            if thumbnails_dir and image:
                file_name = _thumbnail_name(record["relative"], stamp)
                with io.open(os.path.join(thumbnails_dir, file_name), "wb") as f:
                    f.write(image["png"])
                row["thumbnail"] = file_name
        names.setdefault(fold(row["family"]), []).append(row["relative"])
        rows.append(row)
    for row in rows:
        row["duplicate_name"] = len(names[fold(row["family"])]) > 1
    statuses = {}
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    reasons = {}
    for item in skipped:
        reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    return {
        "kind": INDEX_KIND,
        "version": INDEX_VERSION,
        "root": root,
        "thumbnails_dir": thumbnails_dir,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "complete": not skipped and not limits,
        "limits_hit": limits,
        "counts": {
            "families": len(rows),
            "types": sum(len(r["types"]) for r in rows),
            "reused": reused,
            "by_status": statuses,
            "skipped": reasons,
        },
        "skipped": skipped,
        "families": rows,
    }


def write_index(index, path):
    """Write the index next to its final name, then replace it in one step."""
    path = os.path.abspath(path)
    temp = path + ".tmp"
    with io.open(temp, "w", encoding="utf-8") as f:
        f.write(json.dumps(index, ensure_ascii=False, indent=1))
    os.replace(temp, path)


def load_index(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        index = json.load(f)
    if index.get("kind") != INDEX_KIND or index.get("version") != INDEX_VERSION:
        raise ValueError("This file is not a family library index (version %d)." % INDEX_VERSION)
    return index


def parse_parameter_filter(text):
    """'Width=900' -> ('width', '900'); 'Width' -> ('width', None)."""
    if text is None:
        return None
    if "=" in text:
        name, value = text.split("=", 1)
        name, value = name.strip(), value.strip()
    else:
        name, value = text.strip(), None
    if not name:
        raise ValueError("Give a parameter name, for example Width=900.")
    return fold(name), value


def _number(text):
    match = NUMBER.match((text or u"").strip())
    if not match or match.group(0) in ("-", "+", "."):
        return None
    rest = text.strip()[match.end():].strip()
    if rest and not re.match(r"[A-Za-z\"' ]*\Z", rest):
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def value_matches(actual, wanted):
    """Numbers compare by value (900 = 900.0), text compares case-insensitively."""
    a, w = _number(actual), _number(wanted)
    if a is not None and w is not None:
        return abs(a - w) <= 1e-6 * max(1.0, abs(w))
    return fold(actual) == fold(wanted)


def _parameter(type_row, name):
    for parameter in type_row.get("parameters", []):
        if fold(parameter.get("name")) == name:
            return parameter
    return None


def search(index, text=None, category=None, type_name=None, parameter=None,
           include_backups=False, include_unreadable=False, limit=50):
    """Search rows: one row per family type (or one per family with no types).

    text: words that must all appear in the family name, folder or type name.
    category: part of the category name. type_name: part of the type name.
    parameter: (folded name, value or None) from parse_parameter_filter.
    Returns {"rows": [...], "total": n, "truncated": bool}.
    """
    words = [fold(w) for w in (text or u"").split() if w.strip()]
    want_category = fold(category) if category else None
    want_type = fold(type_name) if type_name else None
    limit = max(1, min(int(limit), MAX_RESULTS))
    rows = []
    for family in index.get("families", []):
        if family.get("backup") and not include_backups:
            continue
        if family.get("status") == "unreadable" and not include_unreadable:
            continue
        if want_category and want_category not in fold(family.get("category")):
            continue
        types = family.get("types") or []
        candidates = types if types else [None]
        for type_row in candidates:
            haystack = fold(u" ".join([family["family"], family.get("folder") or u"",
                                       type_row["name"] if type_row else u""]))
            if any(word not in haystack for word in words):
                continue
            if want_type and (type_row is None or want_type not in fold(type_row["name"])):
                continue
            matched = None
            if parameter is not None:
                if type_row is None:
                    continue
                found = _parameter(type_row, parameter[0])
                if found is None:
                    continue
                if parameter[1] is not None and not value_matches(found.get("value"), parameter[1]):
                    continue
                matched = found
            rows.append({
                "family": family["family"],
                "type": type_row["name"] if type_row else None,
                "type_origin": type_row.get("origin") if type_row else None,
                "category": family.get("category"),
                "folder": family.get("folder"),
                "relative": family["relative"],
                "path": os.path.join(index["root"], *family["relative"].split("/")),
                "thumbnail": (os.path.join(index["thumbnails_dir"], family["thumbnail"])
                              if family.get("thumbnail") and index.get("thumbnails_dir") else None),
                "revit_version": family.get("revit_version"),
                "duplicate_name": family.get("duplicate_name", False),
                "status": family.get("status"),
                "parameter": matched,
            })
    total = len(rows)
    return {"rows": rows[:limit], "total": total, "truncated": total > limit}


def mark_in_model(rows, loaded):
    """Add in_model columns from a read_loaded_families.py result.

    family_in_model: a loaded family has the same name (case-insensitive).
    type_in_model: that family also has a type with the same name.
    model_category: the category of the loaded family, for review.
    """
    if "result" in loaded and "families" not in loaded:
        loaded = loaded["result"]
    if not loaded or "families" not in loaded:
        raise ValueError("The model read has no families list (check status and error).")
    by_name = {}
    for family in loaded["families"]:
        name = family.get("name")
        if loaded.get("escaped"):
            name = unescape(name)
        by_name.setdefault(fold(name), []).append(family)
    marked = []
    for row in rows:
        row = dict(row)
        matches = by_name.get(fold(row["family"]), [])
        row["family_in_model"] = bool(matches)
        row["model_category"] = matches[0].get("category") if matches else None
        types = set()
        for family in matches:
            for type_name in family.get("types", []):
                types.add(fold(unescape(type_name) if loaded.get("escaped") else type_name))
        row["type_in_model"] = bool(row["type"]) and fold(row["type"]) in types
        marked.append(row)
    return {"rows": marked, "truncated": bool(loaded.get("truncated"))}


ESCAPED = re.compile(r"\\(\\|u[0-9a-fA-F]{4})")


def unescape(text):
    """Reverse the ASCII escaping of IronPython reads (read_loaded_families.py)."""
    if text is None:
        return None

    def replace(match):
        token = match.group(1)
        if token == "\\":
            return u"\\"
        try:
            return unichr(int(token[1:], 16))  # noqa: F821  (IronPython 2.7)
        except NameError:
            return chr(int(token[1:], 16))
    return ESCAPED.sub(replace, text)


def text_table(result, show_model=False):
    """Compact chat table of search rows."""
    rows = result["rows"]
    if not rows:
        return "No family matches the search."
    header = ["#", "Family", "Type", "Category", "Folder"]
    if show_model:
        header.append("In model")
    header.append("Thumbnail")
    lines = [" | ".join(header), " | ".join("---" for _ in header)]
    for number, row in enumerate(rows, 1):
        cells = [str(number), row["family"] + (" (same name elsewhere)" if row.get("duplicate_name") else ""),
                 row["type"] or "-", row["category"] or "-", row["folder"] or "."]
        if show_model:
            if row.get("type_in_model"):
                cells.append("type loaded")
            elif row.get("family_in_model"):
                cells.append("family loaded, type not")
            else:
                cells.append("no")
        cells.append("yes" if row.get("thumbnail") else "-")
        lines.append(" | ".join(c.replace("|", "/") for c in cells))
    tail = "%d of %d rows." % (len(rows), result.get("total", len(rows)))
    if result.get("truncated"):
        tail += " Narrow the search to see the rest."
    lines.append(tail)
    return "\n".join(lines)

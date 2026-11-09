"""Estimate observed command windows from local Revit journals."""

import argparse
import codecs
from collections import Counter
from datetime import datetime, timedelta
from io import TextIOWrapper
import json
import ntpath
import os
from pathlib import Path
import re


JOURNAL = re.compile(r"journal\.\d+\.txt", re.IGNORECASE)
YEAR_DIR = re.compile(r"Autodesk Revit (20\d\d)", re.IGNORECASE)
MARKER = re.compile(
    r"^\s*'[A-Z] (\d{2})-([A-Za-z]{3})-(\d{4})( \d{2}:\d{2}:\d{2}\.\d{3});"
)
MONTHS = {name: index for index, name in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1
)}
COMMAND = re.compile(r'^\s*Jrn\.Command\s+"[^"]*"\s*,\s*"[^"]*?,\s*(ID_[A-Z0-9_]+)\s*"')
EXTERNAL = re.compile(r'^\s*Jrn\.RibbonEvent\s+"Execute external command:', re.IGNORECASE)
MODEL_OPEN = re.compile(r"\[ISL\] On open, Adler Checksum: \S+ \[(.+\.(?:rvt|rfa))\]", re.IGNORECASE)
CONTEXT_CHANGE = re.compile(r"^\s*Jrn\.(?:Activate|Close)", re.IGNORECASE)
MAX_LINE = 1024 * 1024
MILLISECOND = timedelta(milliseconds=1)
SECOND = timedelta(seconds=1)
FAMILIES = frozenset({"WALL", "FLOOR", "CEILING", "ROOF", "ROOM", "DOOR", "WINDOW",
                      "DIMENSION", "SHEET", "VIEW", "MODIFY", "OBJECTS", "EXTERNAL",
                      "PIPE", "DUCT", "CABLETRAY", "CONDUIT"})


def marker_time(match):
    day, month, year, clock = match.groups()
    return datetime.fromisoformat(f"{year}-{MONTHS[month.lower()]:02d}-{day}{clock}")


def scan_journal(path, start, end, max_gap, encoding):
    with path.open("rb") as stream:
        initial = os.fstat(stream.fileno())
        bom = stream.read(3)
        stream.seek(0)
        if bom.startswith(codecs.BOM_UTF8):
            encoding = "utf-8-sig"
        elif bom.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            encoding = "utf-16"
        observed_models = set()
        active_model = None
        commands = set()
        ambiguous = False
        attributed = Counter()
        unassigned = Counter()
        previous = None
        observed = False
        partial = False
        # Decoded characters cannot outnumber source bytes in the supported encodings.
        remaining = initial.st_size
        with TextIOWrapper(stream, encoding=encoding) as reader:
            while remaining:
                line = reader.readline(min(MAX_LINE, remaining + 1))
                if not line:
                    break
                remaining -= len(line)
                if remaining < 0 or (len(line) == MAX_LINE and not line.endswith("\n")):
                    partial = True
                    break
                if not line.endswith("\n"):
                    partial = True
                    break
                stamp = MARKER.match(line)
                if stamp:
                    try:
                        current = marker_time(stamp)
                    except (ValueError, KeyError):
                        partial = True
                        previous = None
                        commands.clear()
                        ambiguous = False
                        continue
                    observed |= start <= current < end
                    if previous is not None and current < previous:
                        partial = True
                    elif previous is not None and current > previous:
                        duration = min(current, end) - max(previous, start)
                        milliseconds = duration // MILLISECOND
                        if milliseconds > 0:
                            if current - previous > max_gap * SECOND:
                                unassigned["long_gap"] += milliseconds
                            elif ambiguous or len(commands) != 1:
                                unassigned["ambiguous_or_no_command"] += milliseconds
                            else:
                                family = next(iter(commands)).split("_", 1)[0]
                                family = family.lower() if family in FAMILIES else "other"
                                attributed[active_model, family] += milliseconds
                    if previous is None or current != previous:
                        commands.clear()
                        ambiguous = False
                    previous = current
                    continue

                model = MODEL_OPEN.search(line)
                if model:
                    raw = model.group(1)
                    active_model = ntpath.normcase(ntpath.normpath(raw)) if ntpath.isabs(raw) else None
                    if active_model:
                        observed_models.add(active_model)
                    ambiguous = True
                if CONTEXT_CHANGE.match(line):
                    active_model = None
                    ambiguous = True

                command = COMMAND.match(line)
                if command:
                    command_id = command.group(1)[3:]
                    family = command_id.split("_", 1)[0]
                    commands.add(command_id)
                    if family in {"REVIT", "FILE", "WINDOW", "CLOSE"}:
                        active_model = None
                        ambiguous = True
                elif EXTERNAL.match(line):
                    commands.add("EXTERNAL")
                    active_model = None
            final = os.fstat(stream.fileno())
            partial |= (initial.st_size, initial.st_mtime_ns) != (final.st_size, final.st_mtime_ns)
    if partial:
        return "partial", Counter(), Counter()
    if previous is None:
        return "undated", Counter(), Counter()
    if not observed and not attributed and not unassigned:
        return "outside_range", Counter(), Counter()
    # An open record alone cannot identify the active document in a multi-model session.
    if len(observed_models) > 1:
        unattributed_models = Counter()
        for (_, family), duration in attributed.items():
            unattributed_models[None, family] += duration
        attributed = unattributed_models
    return "read", attributed, unassigned


def summarize(root, start, end, max_gap, encoding):
    coverage = Counter()
    groups = Counter()
    unassigned = Counter()
    # Accept a copied Journals directory as well as the standard Revit root.
    directories = [root]
    try:
        directories += [
            p / "Journals" for p in root.iterdir() if YEAR_DIR.fullmatch(p.name) and not p.is_symlink()
        ]
    except OSError:
        directories = []
        coverage["unreadable_directory"] += 1
    for directory in directories:
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            coverage["unreadable_directory"] += 1
            continue
        for path in entries:
            if not JOURNAL.fullmatch(path.name):
                continue
            if path.is_symlink():
                coverage["unreadable"] += 1
                continue
            try:
                state, timed, untimed = scan_journal(path, start, end, max_gap, encoding)
            except (OSError, UnicodeError):
                coverage["unreadable"] += 1
                continue
            coverage[state] += 1
            groups.update(timed)
            unassigned.update(untimed)

    models = {model: f"model-{i}" for i, model in enumerate(
        sorted({model for model, _ in groups if model is not None}), 1
    )}
    rows = [
        {"model": models.get(model), "command_family": family, "estimated_ms": duration}
        for (model, family), duration in sorted(groups.items(), key=lambda row: (row[0][0] or "", row[0][1]))
    ]
    incomplete = any(coverage[key] for key in ("partial", "undated", "unreadable", "unreadable_directory"))
    return {
        "window": {"from": start.isoformat(), "to_exclusive": end.isoformat()},
        "coverage": dict(sorted(coverage.items())),
        "status": "incomplete" if incomplete else "reported" if coverage["read"] else "no_data",
        "activity_windows": rows,
        "unassigned_ms": dict(sorted(unassigned.items())),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = os.environ.get("LOCALAPPDATA")
    parser.add_argument("--root", type=Path, default=Path(default) / "Autodesk" / "Revit" if default else None)
    parser.add_argument("--from", dest="start", type=datetime.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=datetime.fromisoformat, required=True)
    parser.add_argument("--max-gap-seconds", type=int, default=60, choices=range(1, 301), metavar="1–300")
    parser.add_argument("--encoding", choices=("utf-8", "cp1252"), default="utf-8")
    args = parser.parse_args()
    if args.root is None:
        parser.error("--root is required when LOCALAPPDATA is unavailable")
    if args.start.tzinfo or args.end.tzinfo or args.start >= args.end:
        parser.error("use increasing local dates or datetimes without timezone offsets")
    report = summarize(args.root, args.start, args.end, args.max_gap_seconds, args.encoding)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "reported" else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Revit backup file scanner and cleanup tool (Issue #176).

Finds .0001-style Revit backup files (*.0001.rvt, *.0002.rfa, *.0001.rte)
in project directories. Reports file count and disk usage.
Supports dry-run preview, safe archive relocation, and confirmed deletion.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple

BACKUP_PATTERN = re.compile(r"^(.+)\.(\d{4})\.(rvt|rfa|rte)$", re.IGNORECASE)


def is_backup_file(filename: str) -> Optional[Tuple[str, int, str]]:
    """Check if filename matches Revit backup pattern (.0001.rvt/rfa/rte).

    Returns (base_name, backup_number, ext) if match, else None.
    """
    match = BACKUP_PATTERN.match(filename)
    if not match:
        return None
    base_name = match.group(1)
    backup_num = int(match.group(2))
    ext = match.group(3).lower()
    return base_name, backup_num, ext


def scan_backups(root_dir: str, recursive: bool = True) -> List[Dict[str, object]]:
    """Scan directory for Revit backup files."""
    results: List[Dict[str, object]] = []
    if not os.path.isdir(root_dir):
        return results

    if recursive:
        for root, _, files in os.walk(root_dir):
            for f in files:
                parsed = is_backup_file(f)
                if parsed:
                    full_path = os.path.join(root, f)
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        size = 0
                    results.append({
                        "path": os.path.abspath(full_path),
                        "filename": f,
                        "base_name": parsed[0],
                        "backup_num": parsed[1],
                        "extension": parsed[2],
                        "size_bytes": size,
                    })
    else:
        for f in os.listdir(root_dir):
            full_path = os.path.join(root_dir, f)
            if os.path.isfile(full_path):
                parsed = is_backup_file(f)
                if parsed:
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        size = 0
                    results.append({
                        "path": os.path.abspath(full_path),
                        "filename": f,
                        "base_name": parsed[0],
                        "backup_num": parsed[1],
                        "extension": parsed[2],
                        "size_bytes": size,
                    })

    results.sort(key=lambda x: str(x["path"]))
    return results


def format_size(bytes_val: int) -> str:
    """Format bytes into readable MB/KB."""
    if bytes_val >= 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"
    if bytes_val >= 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.2f} MB"
    if bytes_val >= 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{bytes_val} bytes"


def summarize_backups(backups: List[Dict[str, object]]) -> Dict[str, object]:
    """Return summary dictionary for scan results."""
    total_bytes = sum(int(b["size_bytes"]) for b in backups)
    by_ext: Dict[str, int] = {}
    for b in backups:
        ext = str(b["extension"])
        by_ext[ext] = by_ext.get(ext, 0) + 1

    return {
        "count": len(backups),
        "total_bytes": total_bytes,
        "formatted_size": format_size(total_bytes),
        "by_extension": by_ext,
    }


def archive_backups(backups: List[Dict[str, object]], target_dir: str) -> int:
    """Move backup files to target archive directory."""
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)

    moved = 0
    for b in backups:
        src = str(b["path"])
        dst = os.path.join(target_dir, str(b["filename"]))
        if os.path.exists(src):
            shutil.move(src, dst)
            moved += 1
    return moved


def delete_backups(backups: List[Dict[str, object]], confirm: bool = False) -> int:
    """Delete backup files if confirmed."""
    if not confirm:
        raise ValueError("Deletion requires explicit confirm=True")

    deleted = 0
    for b in backups:
        path = str(b["path"])
        if os.path.exists(path):
            os.remove(path)
            deleted += 1
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Find and clean up Revit .0001 backup files.")
    parser.add_argument("directory", help="Root directory to scan")
    parser.add_argument("--no-recursive", action="store_true", help="Scan only the specified directory")
    parser.add_argument("--archive", metavar="ARCHIVE_DIR", help="Move backup files to archive directory")
    parser.add_argument("--delete", action="store_true", help="Delete backup files (requires --confirm)")
    parser.add_argument("--confirm", action="store_true", help="Confirmation flag for destructive operations")

    args = parser.parse_args()

    backups = scan_backups(args.directory, recursive=not args.no_recursive)
    summary = summarize_backups(backups)

    print(f"Scanned: {args.directory}")
    print(f"Found {summary['count']} backup files ({summary['formatted_size']})")
    for ext, count in summary["by_extension"].items():
        print(f"  .{ext}: {count}")

    if not backups:
        return 0

    if args.archive:
        moved = archive_backups(backups, args.archive)
        print(f"Archived {moved} files to {args.archive}")
    elif args.delete:
        if not args.confirm:
            print("Error: --delete requires --confirm flag to prevent accidental loss.", file=sys.stderr)
            return 1
        deleted = delete_backups(backups, confirm=True)
        print(f"Deleted {deleted} backup files.")
    else:
        print("\nDry-run preview (run with --archive <dir> or --delete --confirm to execute):")
        for b in backups[:10]:
            print(f"  {b['filename']} ({format_size(int(b['size_bytes']))})")
        if len(backups) > 10:
            print(f"  ... and {len(backups) - 10} more files")

    return 0


if __name__ == "__main__":
    sys.exit(main())

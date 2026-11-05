import os
import sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from cleanup_backups import (
    is_backup_file,
    scan_backups,
    summarize_backups,
    archive_backups,
    delete_backups,
    format_size,
)


def test_is_backup_file():
    assert is_backup_file("Hospital_Central.0001.rvt") == ("Hospital_Central", 1, "rvt")
    assert is_backup_file("Door-Single.0042.rfa") == ("Door-Single", 42, "rfa")
    assert is_backup_file("Commercial_Template.0005.RTE") == ("Commercial_Template", 5, "rte")

    # Non-backups
    assert is_backup_file("Hospital_Central.rvt") is None
    assert is_backup_file("Door-Single.rfa") is None
    assert is_backup_file("Drawing.dwg") is None
    assert is_backup_file("notes.0001.txt") is None
    assert is_backup_file("version.1.2.3.rvt") is None


def test_scan_and_summarize_backups(tmp_path):
    # Setup test directory tree
    (tmp_path / "Main.rvt").write_text("main")
    (tmp_path / "Main.0001.rvt").write_text("backup 1")
    (tmp_path / "Main.0002.rvt").write_text("backup 2")
    (tmp_path / "Family.rfa").write_text("family")
    (tmp_path / "Family.0001.rfa").write_text("family backup")

    sub = tmp_path / "subfolder"
    sub.mkdir()
    (sub / "Sub.0001.rvt").write_text("sub backup")
    (sub / "ignore.txt").write_text("ignore")

    backups = scan_backups(str(tmp_path), recursive=True)
    assert len(backups) == 4

    summary = summarize_backups(backups)
    assert summary["count"] == 4
    assert summary["by_extension"] == {"rvt": 3, "rfa": 1}
    assert summary["total_bytes"] > 0


def test_archive_backups(tmp_path):
    (tmp_path / "Project.0001.rvt").write_text("backup 1")
    (tmp_path / "Project.rvt").write_text("project active")

    archive_dir = tmp_path / "archive"
    backups = scan_backups(str(tmp_path), recursive=False)
    assert len(backups) == 1

    moved = archive_backups(backups, str(archive_dir))
    assert moved == 1
    assert not (tmp_path / "Project.0001.rvt").exists()
    assert (archive_dir / "Project.0001.rvt").exists()
    assert (tmp_path / "Project.rvt").exists()


def test_delete_backups(tmp_path):
    (tmp_path / "Project.0001.rvt").write_text("backup 1")
    (tmp_path / "Project.rvt").write_text("keep this")

    backups = scan_backups(str(tmp_path))
    assert len(backups) == 1

    # Should raise error without confirm
    with pytest.raises(ValueError):
        delete_backups(backups, confirm=False)

    deleted = delete_backups(backups, confirm=True)
    assert deleted == 1
    assert not (tmp_path / "Project.0001.rvt").exists()
    assert (tmp_path / "Project.rvt").exists()


def test_format_size():
    assert format_size(500) == "500 bytes"
    assert format_size(2048) == "2.0 KB"
    assert format_size(5 * 1024 * 1024) == "5.00 MB"

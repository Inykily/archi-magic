import json
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "keynote_file.py"


def fixture(tmp_path):
    source = tmp_path / "original.txt"
    source.write_bytes("A\tAssembly\r\nA-1\tDoor\tA\r\nA-2\tWindow\tA\r\n".encode("utf-16"))
    usage = tmp_path / "tags.json"
    usage.write_text(json.dumps([{"tag_id": 1, "key": "A-1"}, {"tag_id": 2, "key": "MISSING"}]))
    return source, usage


def run(action, source, usage, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), action, "--keynotes", str(source), "--usage", str(usage), *extra],
        capture_output=True, text=True,
    )


def test_tree_identifies_the_tag_with_a_missing_key_and_unused_leaf(tmp_path):
    source, usage = fixture(tmp_path)
    result = run("audit", source, usage)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert [(row["key"], row["depth"]) for row in data["tree"]] == [("A", 0), ("A-1", 1), ("A-2", 1)]
    assert data["missing_tags"] == [{"tag_id": 2, "key": "MISSING"}]
    assert data["unused_leaf_keys"] == ["A-2"]


def test_stage_preserves_original_and_makes_backup_and_edited_copy(tmp_path):
    source, usage = fixture(tmp_path)
    original = source.read_bytes()
    candidate, output, backup = [tmp_path / name for name in ("candidate.txt", "new.txt", "backup.txt")]
    candidate.write_text("A\tAssembly\nA-1\tDoor\tA\nMISSING\tWall\tA\n", encoding="utf-8")
    args = ("--candidate", str(candidate), "--output", str(output), "--backup", str(backup))
    result = run("stage", source, usage, *args)
    assert result.returncode == 0
    assert backup.read_bytes() == original == source.read_bytes()
    assert output.read_bytes() == candidate.read_bytes()
    assert run("stage", source, usage, *args).returncode == 2
    assert output.read_bytes() == candidate.read_bytes()


def test_stage_rejects_removing_a_used_key_before_writing(tmp_path):
    source, usage = fixture(tmp_path)
    candidate, output, backup = [tmp_path / name for name in ("candidate.txt", "new.txt", "backup.txt")]
    candidate.write_text("A\tAssembly\nA-2\tWindow\tA\n", encoding="utf-8")
    result = run("stage", source, usage, "--candidate", str(candidate), "--output", str(output),
                 "--backup", str(backup))
    assert result.returncode == 2
    assert "removes keys referenced by tags" in result.stderr
    assert not output.exists() and not backup.exists()

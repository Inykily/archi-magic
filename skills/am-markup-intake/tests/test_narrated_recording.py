import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import narrated_recording_cli as cli
import recording_media as media


@pytest.fixture
def draft(tmp_path, monkeypatch, capsys):
    recording = tmp_path / "review.mp4"
    recording.write_bytes(b"fixture recording")
    model = tmp_path / "model.bin"
    model.write_bytes(b"fixture model")
    folder = tmp_path / "preview"

    def analyze(snapshot, work, *_):
        assert snapshot.read_bytes() == recording.read_bytes()
        data = b"fixture frame"
        (work / "frame-001.png").write_bytes(data)
        return (
            [{"narration": "First, check view A101. Second, update this tag.", "start": 1, "end": 3}],
            [{"file": "frame-001.png", "sha256": hashlib.sha256(data).hexdigest(),
              "actual_seconds": 2, "requested_seconds": 2, "reasons": ["click", "speech"]}],
            [],
        )

    monkeypatch.setattr(cli, "analyze_recording", analyze)
    args = ["preview", str(recording), "--out", str(folder), "--model", str(model),
            "--ffmpeg", sys.executable, "--ffprobe", sys.executable, "--whisper", sys.executable]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "needs_review", "item_count": 2, "warnings": [],
    }
    preview = folder / "preview.json"
    decisions = folder / "decisions.json"
    template = json.loads((folder / "review-template.json").read_bytes())
    args = ["review", str(recording), "--preview", str(preview), "--decisions", str(decisions)]
    return recording, preview, decisions, template, args


def save_decisions(draft, choices):
    _, _, decisions, template, args = draft
    template["decisions"] = choices
    decisions.write_bytes(cli.encode(template))
    return args


def test_preview_has_no_ready_tasks_and_review_supports_edit(draft, capsys):
    _, preview, _, _, _ = draft
    doc = json.loads(preview.read_bytes())
    assert set(doc) == {"kind", "status", "items", "frames", "recording_sha256", "warnings"}
    assert [(item["id"], item["references"]) for item in doc["items"]] == [(1, ["view A101"]), (2, [])]
    assert cli.main(save_decisions(draft, [
        {"id": 1, "action": "accept"},
        {"id": 2, "action": "edit", "text": "Update the tag", "references": ["element ID 123"]},
    ])) == 0
    reviewed = json.loads(capsys.readouterr().out)
    assert reviewed["model_write_approved"] is False
    assert [(task["text"], task["references"]) for task in reviewed["tasks"]] == [
        ("First, check view A101.", ["view A101"]), ("Update the tag", ["element ID 123"]),
    ]
    assert [task["source"]["frames"] for task in reviewed["tasks"]] == [doc["frames"], doc["frames"]]


@pytest.mark.parametrize("choices", [
    [{"id": 1, "action": "accept"}],
    [{"id": 1, "action": "accept"}, {"id": 1, "action": "reject"}],
    [{"id": 1, "action": "accept"}, {"id": 2, "action": "accept"}],
    [{"id": 1, "action": "accept", "text": "injected"}, {"id": 2, "action": "reject"}],
])
def test_incomplete_duplicate_unresolved_or_extra_decisions_fail(draft, choices, capsys):
    assert cli.main(save_decisions(draft, choices)) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("target", ["recording", "preview", "frame"])
def test_review_rejects_substituted_evidence(draft, target, capsys):
    recording, preview, _, _, _ = draft
    args = save_decisions(draft, [{"id": 1, "action": "accept"}, {"id": 2, "action": "reject"}])
    path = {"recording": recording, "preview": preview, "frame": preview.parent / "frame-001.png"}[target]
    path.write_bytes(path.read_bytes() + b" ")
    assert cli.main(args) == 2
    assert capsys.readouterr().out == ""


def test_all_rejected_produces_empty_list(draft, capsys):
    assert cli.main(save_decisions(draft, [{"id": n, "action": "reject"} for n in (1, 2)])) == 0
    result = json.loads(capsys.readouterr().out)
    assert (result["status"], result["tasks"], result["model_write_approved"]) == (
        "no_approved_tasks", [], False,
    )


def test_bounded_tool_pipe_and_deadline(tmp_path):
    def run(code, seconds):
        return media.run_tool([sys.executable, "-c", code], time.monotonic() + seconds, cwd=tmp_path)

    assert run("print('probe')", 4) == ("probe\n", "")
    with pytest.raises(ValueError, match="output limit"):
        run("print('x' * 1500000)", 4)
    with pytest.raises(ValueError, match="timed out"):
        run("import time; time.sleep(3)", 0.15)


def test_overflow_does_not_publish_preview(tmp_path, monkeypatch, capsys):
    recording = tmp_path / "review.mp4"
    recording.write_bytes(b"fixture")
    model = tmp_path / "model.bin"
    model.write_bytes(b"fixture")
    out = tmp_path / "preview"

    def analyze(_snapshot, work, *_):
        media.run_tool(
            [sys.executable, "-c", "print('x' * 1500000)"],
            time.monotonic() + 4, cwd=work,
        )

    monkeypatch.setattr(cli, "analyze_recording", analyze)
    assert cli.main([
        "preview", str(recording), "--out", str(out), "--model", str(model),
        "--ffmpeg", sys.executable, "--ffprobe", sys.executable, "--whisper", sys.executable,
    ]) == 2
    assert "output limit" in capsys.readouterr().err
    assert not out.exists()


def test_frame_schedule_and_whisper_padding():
    windows, clips = media.voice_windows(
        "silence_start: 0\nsilence_end: 2\nsilence_start: 4\nsilence_end: 8\nsilence_start: 10\nsilence_end: 12",
        12,
    )
    assert media.frame_times(windows, clips, [6], [9, 11], 12) == [
        (3, {"speech"}), (6, {"pause", "scene_change"}), (9, {"speech", "click"}), (11, {"click"}),
    ]
    assert media.transcript_segments(
        {"transcription": [{"offsets": {"from": 0, "to": 2320}, "text": " Check view A102."}]}, 8, 10
    ) == [{"narration": "Check view A102.", "start": 8, "end": 10}]

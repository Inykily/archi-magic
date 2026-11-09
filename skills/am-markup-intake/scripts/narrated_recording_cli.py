"""Create and review a numbered task list from a local narrated MP4."""

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from recording_media import MAX_OUTPUT, analyze_recording, local_path, read_file, recording_digest

PREVIEW_KIND = "narrated-recording-preview"
DECISIONS_KIND = "narrated-recording-decisions"
FRAME_NAME = re.compile(r"frame-[0-9]{3}\.png")
REFERENCE = re.compile(
    r'\b(element(?:\s+id)?)[ :]+(\d{1,19})\b'
    r'|\b(view|sheet)[ :]+("[^"\r\n]{1,100}"|\{3D\}|[A-Z]{1,4}[-.]?\d[\d.-]{0,12}\b)',
    re.IGNORECASE,
)
NUMBERED_ACTION = re.compile(
    r"\s+(?=(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|next|finally),\s)",
    re.IGNORECASE,
)


def encode(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def proposals(transcript, frames):
    items = []
    for segment in transcript:
        midpoint = (segment["start"] + segment["end"]) / 2
        evidence = [min(frames, key=lambda frame: abs(frame["actual_seconds"] - midpoint))]
        for reason in ("click", "scene_change"):
            nearby = [frame for frame in frames if reason in frame["reasons"] and
                      segment["start"] - 2 <= frame["actual_seconds"] <= segment["end"] + 2]
            if nearby:
                evidence.append(min(nearby, key=lambda frame: abs(frame["actual_seconds"] - midpoint)))

        for phrase in NUMBERED_ACTION.split(segment["narration"]):
            references = []
            for match in REFERENCE.finditer(phrase):
                element, element_id, kind, name = match.groups()
                if element:
                    reference = f"element ID {element_id}"
                else:
                    name = name.strip('"')
                    reference = f"{kind.lower()} {name}"
                if reference not in references:
                    references.append(reference)
            items.append({
                "id": len(items) + 1, "text": phrase, "references": references,
                "source": {**segment, "frames": sorted({frame["file"] for frame in evidence})},
            })
    return items


def publish(directory, work, preview):
    preview_bytes = encode(preview)
    if len(preview_bytes) > MAX_OUTPUT:
        raise ValueError("Preview exceeds the byte limit. Use a shorter recording.")
    template = {
        "kind": DECISIONS_KIND,
        "preview_sha256": hashlib.sha256(preview_bytes).hexdigest(),
        "decisions": [{"id": item["id"], "action": ""} for item in preview["items"]],
    }
    directory.mkdir(mode=0o700)
    created = []
    try:
        for frame in preview["frames"]:
            filename = frame["file"]
            with (directory / filename).open("xb") as output:
                created.append(directory / filename)
                output.write(read_file(work / filename, MAX_OUTPUT))
        for filename, content in (
            ("review-template.json", encode(template)),
            ("preview.json", preview_bytes),
        ):
            with (directory / filename).open("xb") as output:
                created.append(directory / filename)
                output.write(content)
    except BaseException:
        for path in created:
            path.unlink()
        directory.rmdir()
        raise


def preview_recording(args):
    recording = local_path(args.recording)
    directory = local_path(args.out)
    if directory.exists() or not directory.parent.is_dir():
        raise ValueError("Use a new output directory inside an existing local folder.")
    model = local_path(args.model)
    if not model.is_file() or not 0 < model.stat().st_size <= 2 * 1024**3:
        raise ValueError("Use an existing local Whisper model up to 2 GiB.")
    tools = []
    for binary in (args.ffmpeg, args.ffprobe, args.whisper):
        executable = shutil.which(binary)
        if not executable:
            raise ValueError("Set the path to an installed local FFmpeg, ffprobe and whisper-cli.")
        tools.append(str(Path(executable).resolve()))

    with tempfile.TemporaryDirectory(prefix="archi-narration-") as temp:
        work = Path(temp)
        snapshot = work / "recording.mp4"
        with snapshot.open("xb") as output:
            digest = recording_digest(recording, output)
        transcript, frames, warnings = analyze_recording(snapshot, work, *tools, model, args.click_time)
        items = proposals(transcript, frames)
        if not 1 <= len(items) <= 100:
            raise ValueError("Use a recording with 1 to 100 proposed items.")
        publish(directory, work, {
            "kind": PREVIEW_KIND, "status": "needs_review", "recording_sha256": digest,
            "items": items, "frames": frames, "warnings": warnings,
        })
    return {"status": "needs_review", "item_count": len(items), "warnings": warnings}


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON contains a repeated field.")
        result[key] = value
    return result


def valid_text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 2000


def validate_evidence(preview, folder, recording):
    if preview["recording_sha256"] != recording_digest(recording):
        raise ValueError("The recording does not match this preview.")
    frames = {}
    for frame in preview["frames"]:
        filename = frame["file"]
        if not FRAME_NAME.fullmatch(filename) or filename in frames:
            raise ValueError("Preview has an invalid or repeated frame path.")
        frames[filename] = frame
        if hashlib.sha256(read_file(folder / filename, MAX_OUTPUT)).hexdigest() != frame["sha256"]:
            raise ValueError("A preview frame has changed.")
    for item in preview["items"]:
        attached = item["source"]["frames"]
        if not attached or any(name not in frames for name in attached):
            raise ValueError("A preview item has no verified frame evidence.")
    return frames


def review_recording(args):
    preview_path = local_path(args.preview)
    raw_preview = read_file(preview_path, MAX_OUTPUT)
    preview = json.loads(raw_preview, object_pairs_hook=unique_keys)
    document = json.loads(read_file(local_path(args.decisions), MAX_OUTPUT), object_pairs_hook=unique_keys)
    if preview["kind"] != PREVIEW_KIND or preview["status"] != "needs_review":
        raise ValueError("Use an unreviewed narrated recording preview.")
    if (
        set(document) != {"kind", "preview_sha256", "decisions"}
        or document["kind"] != DECISIONS_KIND
        or document["preview_sha256"] != hashlib.sha256(raw_preview).hexdigest()
    ):
        raise ValueError("Decisions must refer to these exact preview bytes.")
    items = preview["items"]
    choices = {}
    for decision in document["decisions"]:
        number, action = decision["id"], decision["action"]
        if type(number) is not int or number in choices:
            raise ValueError("Use one decision per item number.")
        fields = {"id", "action"}
        if action == "edit":
            fields.update(("text", "references"))
        elif action not in ("accept", "reject"):
            raise ValueError("Every item needs accept, edit or reject.")
        if set(decision) != fields:
            raise ValueError("A decision has missing or extra fields.")
        choices[number] = decision
    item_ids = [item["id"] for item in items]
    if item_ids != list(range(1, len(items) + 1)) or not items or set(choices) != set(item_ids):
        raise ValueError("Every preview item needs exactly one decision.")
    frames = validate_evidence(preview, preview_path.parent, local_path(args.recording))
    tasks = []
    for item in items:
        decision = choices[item["id"]]
        if decision["action"] == "reject":
            continue
        text = decision.get("text", item["text"])
        references = decision.get("references", item["references"])
        if not (
            valid_text(text) and isinstance(references, list) and 1 <= len(references) <= 12
            and all(valid_text(reference) for reference in references)
        ):
            raise ValueError(f"Edit item {item['id']} with a concrete reference, or reject it.")
        source = item["source"]
        tasks.append({
            "id": item["id"], "text": text.strip(),
            "references": [reference.strip() for reference in references],
            "source": {**source, "frames": [frames[name] for name in source["frames"]]},
        })
    return {
        "kind": "narrated-recording-reviewed", "status": "reviewed" if tasks else "no_approved_tasks",
        "model_write_approved": False, "recording_sha256": preview["recording_sha256"],
        "preview_sha256": document["preview_sha256"], "tasks": tasks,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview")
    preview.add_argument("recording")
    preview.add_argument("--out", required=True)
    preview.add_argument("--model", required=True)
    preview.add_argument("--whisper", default="whisper-cli")
    preview.add_argument("--ffmpeg", default="ffmpeg")
    preview.add_argument("--ffprobe", default="ffprobe")
    preview.add_argument("--click-time", type=float, action="append", default=[])
    review = commands.add_parser("review")
    review.add_argument("recording")
    review.add_argument("--preview", required=True)
    review.add_argument("--decisions", required=True)
    args = parser.parse_args(argv)
    try:
        result = preview_recording(args) if args.command == "preview" else review_recording(args)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError, RecursionError) as error:
        print(f"Narrated recording intake failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

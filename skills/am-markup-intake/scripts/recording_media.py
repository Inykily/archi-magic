"""Bounded, local media analysis for narrated markup intake."""

import hashlib
import json
import re
import stat
import subprocess
import threading
import time
from fractions import Fraction
from pathlib import Path

MAX_RECORDING = 256 * 1024 * 1024
MAX_OUTPUT = 1024 * 1024
FRAME_SCALE = "scale=320:320:force_original_aspect_ratio=decrease:force_divisible_by=2"
MOV_INPUT = [
    "-protocol_whitelist", "file,pipe", "-enable_drefs", "0",
    "-use_absolute_path", "0", "-f", "mov",
]


def local_path(value):
    if value.startswith(("//", "\\")) or re.match(r"^[a-zA-Z][\w+.-]*:", value):
        if not re.match(r"^[a-zA-Z]:[/\\]", value):
            raise ValueError("Use a local filesystem path.")
    path = Path(value).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Use the original local file or directory path.")
    return path.resolve()


def read_file(path, limit):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Expected a regular file: {path.name}")
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"File exceeds the byte limit: {path.name}")
    return data


def recording_digest(path, snapshot=None):
    if path.suffix.lower() != ".mp4" or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Use a regular local MP4 file.")
    if path.stat().st_size > MAX_RECORDING:
        raise ValueError("Recording exceeds 256 MiB.")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        before = path.stat()
        written = 0
        while chunk := source.read(MAX_OUTPUT):
            written += len(chunk)
            if written > MAX_RECORDING:
                raise ValueError("Recording exceeds 256 MiB.")
            digest.update(chunk)
            if snapshot is not None:
                snapshot.write(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino
        ) or written != before.st_size:
            raise ValueError("Recording changed while it was being read.")
    return digest.hexdigest()


def run_tool(args, deadline, *, cwd, watched_file=None):
    if time.monotonic() >= deadline:
        raise ValueError("Local media processing timed out.")
    buffers = (bytearray(), bytearray())
    overflow = threading.Event()

    def drain(stream, buffer):
        with stream:
            while chunk := stream.read1(16384):
                if len(buffer) + len(chunk) > MAX_OUTPUT:
                    overflow.set()
                    return
                buffer.extend(chunk)

    with subprocess.Popen(
        args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as process:
        readers = [
            threading.Thread(target=drain, args=(stream, buffer), daemon=True)
            for stream, buffer in zip((process.stdout, process.stderr), buffers)
        ]
        for reader in readers:
            reader.start()
        failure = None
        while process.poll() is None:
            if overflow.is_set() or (
                watched_file and watched_file.exists() and watched_file.stat().st_size > MAX_OUTPUT
            ):
                failure = "Local media tool exceeded its output limit."
                break
            if time.monotonic() >= deadline:
                failure = "Local media processing timed out."
                break
            overflow.wait(0.02)
        if failure:
            process.kill()
        process.wait()
        for reader in readers:
            reader.join()
        if overflow.is_set():
            failure = "Local media tool exceeded its output limit."
        if failure:
            raise ValueError(failure)
        if process.returncode:
            raise ValueError(f"{Path(args[0]).name} failed (exit {process.returncode}).")
    return tuple(buffer.decode("utf-8", errors="replace") for buffer in buffers)


def media_duration(probe):
    streams = probe["streams"]
    if sorted(stream["codec_type"] for stream in streams) != ["audio", "video"]:
        raise ValueError("The recording needs exactly one video and one audio stream.")
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    duration = float(probe["format"]["duration"])
    if not 0 < duration <= 300:
        raise ValueError("The recording must be at most five minutes.")
    for stream in [probe["format"], *streams]:
        if not abs(float(stream["start_time"])) <= 0.05:
            raise ValueError("Export the recording with audio and video starting together at zero.")
    if not (
        2 <= video["width"] <= 3840 and 2 <= video["height"] <= 2160
        and 0 < Fraction(video["avg_frame_rate"]) <= 60
    ):
        raise ValueError("Use video up to 3840×2160 and 60 frames per second.")
    return duration


def voice_windows(log, duration):
    start = 0.0
    windows = []
    for kind, timestamp in re.findall(r"silence_(start|end):\s*(-?[\d.]+)", log):
        timestamp = max(0.0, min(float(timestamp), duration))
        if kind == "start" and timestamp > start:
            windows.append((start, timestamp))
        start = duration if kind == "start" else timestamp
    if start < duration:
        windows.append((start, duration))

    clips = []
    for start, end in windows:
        while end - start > 20:
            clips.append((start, start + 20))
            start += 20
        if end > start:
            clips.append((start, end))
    if not 1 <= len(clips) <= 24:
        raise ValueError("Use a recording with 1 to 24 spoken segments.")
    return windows, clips


def transcript_segments(result, start, end):
    segments = []
    previous_end = 0
    for segment in result["transcription"]:
        first, last = (segment["offsets"][key] for key in ("from", "to"))
        if (
            type(first) is not int or type(last) is not int
            or not previous_end <= first < last
            or first >= (end - start) * 1000 or last > (end - start + 0.5) * 1000
        ):
            raise ValueError("Local transcription returned invalid timing.")
        # Whisper can round the last timestamp into its trailing decoder padding.
        spoken = segment["text"].strip()
        if spoken:
            segments.append({
                "narration": spoken, "start": round(start + first / 1000, 3),
                "end": round(min(end, start + last / 1000), 3),
            })
        previous_end = last
    if not segments:
        raise ValueError("Local transcription returned no text for a spoken segment.")
    return segments


def frame_times(windows, clips, scenes, clicks, duration):
    times = {}

    def sample(timestamp, reason):
        if not 0 <= timestamp < duration:
            raise ValueError("Frame timestamp is outside the recording.")
        times.setdefault(round(min(timestamp, duration - min(0.25, duration / 2)), 3), set()).add(reason)

    for start, end in clips:
        sample((start + end) / 2, "speech")
    for (_, end), (start, _) in zip(windows, windows[1:]):
        sample((end + start) / 2, "pause")
    for timestamp in scenes:
        sample(timestamp, "scene_change")
    for timestamp in clicks:
        sample(timestamp, "click")
    if len(times) > 48:
        raise ValueError("Too many frame samples. Use a shorter recording or fewer click times.")
    return sorted(times.items())


def analyze_recording(recording, work, ffmpeg, ffprobe, whisper, model, clicks):
    deadline = time.monotonic() + 180

    def run(args, watched_file=None):
        return run_tool(args, deadline, cwd=work, watched_file=watched_file)

    source = MOV_INPUT + ["-i", str(recording)]
    probe, _ = run([
        ffprobe, "-v", "error", *source, "-show_entries",
        "format=duration,start_time:stream=codec_type,start_time,width,height,avg_frame_rate",
        "-of", "json",
    ])
    duration = media_duration(json.loads(probe))
    ff = [ffmpeg, "-nostdin", "-hide_banner", "-xerror", "-threads", "2", "-filter_threads", "2",
          "-max_pixels", str(3840 * 2160)]
    audio = ["-map", "0:a:0", "-vn", "-sn", "-dn"]
    video = ["-map", "0:v:0", "-an", "-sn", "-dn"]
    _, silence = run([*ff, *source, *audio, "-af", "silencedetect=noise=-42dB:d=0.7", "-f", "null", "-"])
    _, scenes_log = run([
        *ff, *source, *video, "-vf", f"fps=4,{FRAME_SCALE},scdet=t=3", "-f", "null", "-",
    ])
    windows, clips = voice_windows(silence, duration)
    scenes = [float(ts) for ts in re.findall(r"lavfi\.scd\.time:\s*([\d.]+)", scenes_log)]
    if len(clicks) > 48:
        raise ValueError("Use at most 48 click timestamps.")
    samples = frame_times(windows, clips, scenes, clicks, duration)
    transcript = []
    for start, end in clips:
        wav = work / "speech.wav"
        prefix = work / "speech"
        output = prefix.with_suffix(".json")
        run([
            *ff, "-ss", str(start), *source, *audio, "-t", str(end - start),
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav),
        ], wav)
        run([
            whisper, "-m", str(model), "-f", str(wav), "-ng", "-l", "en", "-t", "4",
            "-nf", "-sns", "-oj", "-of", str(prefix),
        ], output)
        transcript.extend(transcript_segments(json.loads(read_file(output, MAX_OUTPUT)), start, end))
        wav.unlink()
        output.unlink()

    frames = []
    for index, (timestamp, reasons) in enumerate(samples, 1):
        filename = f"frame-{index:03}.png"
        frame = work / filename
        _, log = run([
            *ff, "-ss", str(timestamp), "-copyts", *source, *video,
            "-vf", f"{FRAME_SCALE},showinfo", "-frames:v", "1", "-update", "1", str(frame),
        ], frame)
        actual = re.search(r"\bpts_time:([\d.]+(?:e[+-]?\d+)?)\s", log)
        if not actual or not 0 <= float(actual[1]) <= duration:
            raise ValueError("Could not verify the decoded frame time.")
        data = read_file(frame, MAX_OUTPUT)
        frames.append({
            "file": filename, "requested_seconds": timestamp, "actual_seconds": float(actual[1]),
            "reasons": sorted(reasons), "sha256": hashlib.sha256(data).hexdigest(),
        })
    warnings = []
    if len(clips) > len(windows):
        warnings.append("A long spoken segment was split into clips. Review for split or repeated requests.")
    return transcript, frames, warnings

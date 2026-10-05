# -*- coding: utf-8 -*-
"""ffmpeg/ffprobe helpers: probing, voice-sample cleanup, footage looping, labelling."""
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

FFMPEG = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
H264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]


class MediaError(RuntimeError):
    pass


def require_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise MediaError("{} not found on PATH; install ffmpeg first".format(tool))


def _run(args, timeout=None):
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise MediaError("{} failed (exit {}): {}".format(args[0], proc.returncode, proc.stderr[-1500:]))
    return proc


@dataclass
class MediaInfo:
    duration: float
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0
    fps: float = 0.0
    sample_rate: int = 0
    channels: int = 0


def _ratio(value):
    try:
        num, _, den = value.partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path):
    proc = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    data = json.loads(proc.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    try:
        duration = float(data.get("format", {}).get("duration", 0))
    except ValueError:
        duration = 0.0
    info = MediaInfo(duration=duration, has_video=video is not None, has_audio=audio is not None)
    if video:
        info.width, info.height = int(video.get("width", 0)), int(video.get("height", 0))
        info.fps = _ratio(video.get("avg_frame_rate", "0/1"))
    if audio:
        info.sample_rate = int(audio.get("sample_rate", 0))
        info.channels = int(audio.get("channels", 0))
    return info


def volume_stats(path):
    """Return (mean_volume_db, max_volume_db) from ffmpeg's volumedetect."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    mean = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", proc.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", proc.stderr)
    if proc.returncode != 0 or not mean or not peak:
        raise MediaError("volumedetect failed for {}: {}".format(path, proc.stderr[-500:]))
    return float(mean.group(1)), float(peak.group(1))


# Trim leading/trailing silence (reverse trick) and cut rumble, then
# normalise to -18 LUFS in a second pass: chaining loudnorm after
# silenceremove+areverse in one graph deadlocks ffmpeg 6.1. No spectral
# denoise: its artefacts get cloned into the voice.
_TRIM_AF = (
    "highpass=f=70,"
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.25,areverse,"
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.25,areverse"
)
_LOUDNESS_AF = "loudnorm=I=-18:TP=-2:LRA=11"


def clean_voice_sample(src, dst):
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        trimmed = Path(tmp) / "trimmed.wav"
        _run(FFMPEG + ["-i", str(src), "-af", _TRIM_AF, "-c:a", "pcm_s16le", str(trimmed)], timeout=600)
        _run(FFMPEG + ["-i", str(trimmed), "-af", _LOUDNESS_AF, "-ac", "1", "-ar", "44100",
                       "-c:a", "pcm_s16le", str(dst)], timeout=600)
    return Path(dst)


def silent_audio(dst, seconds):
    _run(FFMPEG + ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "{:.3f}".format(seconds),
                   "-c:a", "libmp3lame", "-b:a", "128k", str(dst)])
    return Path(dst)


def _concat_list(paths, list_file):
    lines = ["file '{}'".format(str(Path(p).resolve()).replace("'", "'\\''")) for p in paths]
    Path(list_file).write_text("\n".join(lines) + "\n", encoding="utf-8")


def concat_audio(parts, dst):
    """Join MP3 parts into one MP3 (re-encoded, so frame boundaries can't click)."""
    with tempfile.TemporaryDirectory() as tmp:
        list_file = Path(tmp) / "parts.txt"
        _concat_list(parts, list_file)
        _run(FFMPEG + ["-f", "concat", "-safe", "0", "-i", str(list_file),
                       "-c:a", "libmp3lame", "-b:a", "128k", str(dst)])
    return Path(dst)


def fit_video_to_duration(src, seconds, dst, segment_s=2.0):
    """Make a silent clip of exactly `seconds` from base footage.

    Footage shorter than the target is looped forward-then-reverse
    ("ping-pong") so there is no jump cut at the loop point. Reversal is
    done per short segment so memory stays flat for long 1080p/4K footage
    (ffmpeg's reverse filter buffers every decoded frame).
    """
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    if not info.has_video:
        raise MediaError("{} has no video stream".format(src))
    if info.duration >= seconds:
        _run(FFMPEG + ["-i", str(src), "-an", "-t", "{:.3f}".format(seconds)] + H264 + [str(dst)])
        return dst
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fwd = tmp / "fwd.mp4"
        _run(FFMPEG + ["-i", str(src), "-an", "-force_key_frames",
                       "expr:gte(t,n_forced*{})".format(segment_s)] + H264 + [str(fwd)])
        _run(FFMPEG + ["-i", str(fwd), "-c", "copy", "-f", "segment", "-segment_time", str(segment_s),
                       "-reset_timestamps", "1", str(tmp / "seg_%04d.mp4")])
        segments = sorted(tmp.glob("seg_*.mp4"))
        reversed_parts = []
        for seg in reversed(segments):
            out = tmp / ("rev_" + seg.name)
            _run(FFMPEG + ["-i", str(seg), "-vf", "reverse"] + H264 + [str(out)])
            reversed_parts.append(out)
        list_file = tmp / "pingpong.txt"
        _concat_list([fwd] + reversed_parts, list_file)
        pingpong = tmp / "pingpong.mp4"
        _run(FFMPEG + ["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(pingpong)])
        _run(FFMPEG + ["-stream_loop", "-1", "-i", str(pingpong), "-an", "-t", "{:.3f}".format(seconds)]
             + H264 + [str(dst)])
    return dst


def _filter_escape(value):
    return str(value).replace("\\", "/" if os.name == "nt" else "\\\\").replace(":", "\\:").replace("'", "\\'")


def default_font():
    if os.name == "nt":
        candidate = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"
        return str(candidate) if candidate.exists() else None
    return None  # Linux/macOS ffmpeg builds resolve a default via fontconfig


def burn_label(src, dst, text, font_file=None, metadata=None):
    """Burn a visible disclosure label into the video and tag container metadata."""
    with tempfile.TemporaryDirectory() as tmp:
        text_file = Path(tmp) / "label.txt"
        text_file.write_text(text, encoding="utf-8")
        opts = [
            "textfile='{}'".format(_filter_escape(text_file)),
            "fontsize=h/32", "fontcolor=white", "box=1", "boxcolor=black@0.55",
            "boxborderw=12", "x=w-tw-32", "y=h-th-32",
        ]
        font_file = font_file or default_font()
        if font_file:
            opts.insert(1, "fontfile='{}'".format(_filter_escape(font_file)))
        args = FFMPEG + ["-i", str(src), "-vf", "drawtext=" + ":".join(opts)] + H264 + ["-c:a", "copy"]
        for key, value in (metadata or {}).items():
            args += ["-metadata", "{}={}".format(key, value)]
        _run(args + ["-movflags", "+faststart", str(dst)])
    return Path(dst)

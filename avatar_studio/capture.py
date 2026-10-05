# -*- coding: utf-8 -*-
"""Pre-flight checks on your recordings before anything is uploaded or billed."""
from dataclasses import dataclass
from pathlib import Path

from . import media
from .voice import AUDIO_SUFFIXES


@dataclass
class Finding:
    level: str  # "error" | "warn" | "ok"
    subject: str
    message: str


def audio_files(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES)


def check_voice_samples(folder):
    files = audio_files(folder)
    if not files:
        return [Finding("error", str(folder), "no voice samples found ({})".format(", ".join(sorted(AUDIO_SUFFIXES))))]
    findings, total = [], 0.0
    for path in files:
        info = media.probe(path)
        total += info.duration
        name = path.name
        if info.sample_rate < 22050:
            findings.append(Finding("error", name, "sample rate {} Hz; record at 44.1/48 kHz".format(info.sample_rate)))
        elif info.sample_rate < 44100:
            findings.append(Finding("warn", name, "sample rate {} Hz; 44.1/48 kHz clones better".format(info.sample_rate)))
        if info.duration < 20:
            findings.append(Finding("warn", name, "{:.0f}s clip; aim for 30-120s per clip".format(info.duration)))
        mean_db, peak_db = media.volume_stats(path)
        if peak_db > -0.5:
            findings.append(Finding("warn", name, "peaks at {:.1f} dBFS: likely clipping, re-record lower".format(peak_db)))
        if mean_db < -35:
            findings.append(Finding("warn", name, "mean {:.1f} dBFS: too quiet, move closer to the mic".format(mean_db)))
    if total < 60:
        findings.append(Finding("error", "voice total", "{:.0f}s of audio; instant cloning needs at least 60s".format(total)))
    elif total < 120:
        findings.append(Finding("warn", "voice total", "{:.0f}s of audio; 2-3 minutes gives a closer clone".format(total)))
    else:
        findings.append(Finding("ok", "voice total", "{:.0f}s across {} clip(s)".format(total, len(files))))
    if total > 600:
        findings.append(Finding("warn", "voice total",
                                "over 10 min: instant cloning won't use it all; consider Professional Voice Cloning"))
    return findings


def check_footage(path):
    path = Path(path)
    if not path.exists():
        return [Finding("error", path.name, "base footage not found")]
    info = media.probe(path)
    if not info.has_video:
        return [Finding("error", path.name, "no video stream")]
    findings = []
    short_side = min(info.width, info.height)
    if short_side < 720:
        findings.append(Finding("error", path.name, "{}x{}; record at least 1080p".format(info.width, info.height)))
    elif short_side < 1080:
        findings.append(Finding("warn", path.name, "{}x{}; 1080p or 4K gives a sharper mouth".format(info.width, info.height)))
    if info.fps < 24:
        findings.append(Finding("warn", path.name, "{:.1f} fps; record at 25 or 30 fps".format(info.fps)))
    if info.duration < 8:
        findings.append(Finding("error", path.name, "{:.1f}s; record at least 15-30s of continuous footage".format(info.duration)))
    elif info.duration < 15:
        findings.append(Finding("warn", path.name, "{:.1f}s; loops are visible on short footage, aim for 30-60s".format(info.duration)))
    if not findings:
        findings.append(Finding("ok", path.name, "{}x{} @ {:.0f} fps, {:.0f}s".format(info.width, info.height, info.fps, info.duration)))
    return findings


def check_photo(path):
    path = Path(path)
    if not path.exists():
        return []
    info = media.probe(path)
    short_side = min(info.width, info.height)
    if short_side < 720:
        return [Finding("warn", path.name, "{}x{}; use a 1080px+ photo for a photo avatar".format(info.width, info.height))]
    return [Finding("ok", path.name, "{}x{}".format(info.width, info.height))]

# -*- coding: utf-8 -*-
"""Self-hosted backend: run an open-source lip-sync model on your own GPU.

Your face/body footage and voice never leave the machine. The model is
invoked through a command template from config ([video.local].command),
with {video}, {audio} and {output} replaced by absolute paths, so any
video-to-video lip-sync model (LatentSync, MuseTalk, ...) can be plugged
in without code changes.
"""
import subprocess
from pathlib import Path

from . import media


class LocalBackendError(RuntimeError):
    pass


def build_command(template, video, audio, output):
    if not template:
        raise LocalBackendError("set [video.local].command (see avatar.example.toml)")
    values = {"{video}": str(Path(video).resolve()), "{audio}": str(Path(audio).resolve()),
              "{output}": str(Path(output).resolve())}
    joined = " ".join(template)
    for placeholder in ("{audio}", "{output}"):
        if placeholder not in joined:
            raise LocalBackendError("command template must contain {}".format(placeholder))
    command = []
    for token in template:
        for placeholder, value in values.items():
            token = token.replace(placeholder, value)
        command.append(token)
    return command


def render(cfg, base_video, audio_path, out_path, dry_run=False, log=print):
    base_video, out_path = Path(base_video), Path(out_path)
    if not base_video.exists():
        raise LocalBackendError("base footage not found: {}".format(base_video))
    video = base_video
    if cfg.fit_base_video:
        # Pad 0.5 s so the model never runs out of frames before the audio ends.
        target = media.probe(audio_path).duration + 0.5
        video = out_path.with_name(out_path.stem + "_base.mp4")
        log("fitting base footage to {:.1f}s -> {}".format(target, video.name))
        media.fit_video_to_duration(base_video, target, video)
    command = build_command(cfg.command, video, audio_path, out_path)
    if dry_run:
        log("[dry-run] would run: {}".format(subprocess.list2cmdline(command)))
        return None
    log("running local lip-sync: {}".format(command[0]))
    proc = subprocess.run(command, cwd=cfg.workdir or None, capture_output=True, text=True,
                          timeout=cfg.timeout_s)
    if proc.returncode != 0:
        raise LocalBackendError("lip-sync command failed (exit {}): {}".format(
            proc.returncode, (proc.stderr or proc.stdout)[-2000:]))
    if not out_path.exists():
        raise LocalBackendError("lip-sync command succeeded but wrote no {}".format(out_path))
    return out_path

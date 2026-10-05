# -*- coding: utf-8 -*-
"""CLI: python -m avatar_studio --config avatar.toml <command>"""
import argparse
import sys
from pathlib import Path

import httpx

from . import capture, media, pipeline
from .config import ConfigError, load_config


def _check(cfg, args):
    findings = capture.check_voice_samples(cfg.paths.voice_samples)
    if cfg.backend == "local" or cfg.paths.base_video.exists():
        findings += capture.check_footage(cfg.paths.base_video)
    findings += capture.check_photo(cfg.paths.photo)
    for f in findings:
        print("[{:5}] {}: {}".format(f.level.upper(), f.subject, f.message))
    return 1 if any(f.level == "error" for f in findings) else 0


def _speak(cfg, args):
    out = Path(args.out or cfg.paths.output_dir / (Path(args.text_file).stem + ".mp3"))
    out.parent.mkdir(parents=True, exist_ok=True)
    pipeline.speak(cfg, Path(args.text_file).read_text(encoding="utf-8"), out, args.dry_run)
    print(out)
    return 0


def _render(cfg, args):
    out = Path(args.out or cfg.paths.output_dir / (Path(args.audio).stem + ".mp4"))
    out.parent.mkdir(parents=True, exist_ok=True)
    raw, _ = pipeline.render(cfg, Path(args.audio), out.with_name(out.stem + "_raw.mp4"), args.dry_run)
    if raw is not None:
        pipeline.label(cfg, raw, out)
        print(out)
    return 0


def _prep_voice(cfg, args):
    pipeline.prep_voice(cfg)
    return 0


def _clone_voice(cfg, args):
    pipeline.clone_voice(cfg, args.dry_run)
    return 0


def _make(cfg, args):
    pipeline.make(cfg, args.text_file, args.dry_run)
    return 0


COMMANDS = {
    "check": (_check, "validate voice samples, footage and photo"),
    "prep-voice": (_prep_voice, "clean samples into paths.voice_clean"),
    "clone-voice": (_clone_voice, "create your ElevenLabs voice clone"),
    "speak": (_speak, "text file -> MP3 in your voice"),
    "render": (_render, "MP3 -> lip-synced, labelled MP4"),
    "make": (_make, "text file -> finished video"),
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="avatar_studio", description=__doc__)
    parser.add_argument("--config", default="avatar.toml")
    parser.add_argument("--dry-run", action="store_true",
                        help="no API calls or billing; TTS becomes silence of the right length")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        p = sub.add_parser(name, help=help_text)
        if name in ("speak", "make"):
            p.add_argument("text_file")
        if name == "render":
            p.add_argument("audio")
        if name in ("speak", "render"):
            p.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        media.require_ffmpeg()
        cfg = load_config(args.config)
        return COMMANDS[args.command][0](cfg, args)
    except (ConfigError, media.MediaError, RuntimeError, ValueError, httpx.HTTPError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

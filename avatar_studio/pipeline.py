# -*- coding: utf-8 -*-
"""Orchestration: prep -> clone -> speak -> render -> label, with a provenance manifest."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import capture, heygen, local, media, voice
from .config import api_key

STATE_FILE = "state.json"


def _state_path(cfg):
    return cfg.paths.output_dir / STATE_FILE


def load_state(cfg):
    path = _state_path(cfg)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(cfg, **values):
    state = load_state(cfg)
    state.update(values)
    path = _state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def resolve_voice_id(cfg, dry_run=False):
    voice_id = cfg.voice.voice_id or load_state(cfg).get("voice_id", "")
    if not voice_id and dry_run:
        return "dry-run-voice"
    if not voice_id:
        raise RuntimeError("no voice yet: run `clone-voice`, or set voice.voice_id")
    return voice_id


def prep_voice(cfg, log=print):
    sources = capture.audio_files(cfg.paths.voice_samples)
    if not sources:
        raise RuntimeError("no voice samples in {}".format(cfg.paths.voice_samples))
    cleaned = []
    for src in sources:
        dst = cfg.paths.voice_clean / (src.stem + ".wav")
        media.clean_voice_sample(src, dst)
        log("cleaned {} -> {}".format(src.name, dst))
        cleaned.append(dst)
    return cleaned


def clone_voice(cfg, dry_run=False, log=print):
    samples = capture.audio_files(cfg.paths.voice_clean) or capture.audio_files(cfg.paths.voice_samples)
    if not samples:
        raise RuntimeError("no voice samples; record them and run `prep-voice` first")
    client = voice.ElevenLabs(api_key("ELEVENLABS_API_KEY", dry_run), cfg.voice.base_url, dry_run, log=log)
    try:
        result = client.create_ivc(cfg.voice.name, samples, cfg.voice.description,
                                   labels={"language": cfg.voice.language},
                                   remove_background_noise=cfg.voice.remove_background_noise)
    finally:
        client.close()
    if result.get("requires_verification"):
        log("ElevenLabs requires verification for this voice: complete it in the web app before use")
    if not dry_run:
        save_state(cfg, voice_id=result["voice_id"])
    log("voice_id: {}".format(result["voice_id"]))
    return result["voice_id"]


def speak(cfg, text, out_audio, dry_run=False, log=print):
    voice_id = resolve_voice_id(cfg, dry_run)
    client = voice.ElevenLabs(api_key("ELEVENLABS_API_KEY", dry_run), cfg.voice.base_url, dry_run, log=log)
    try:
        return voice.synthesize(client, cfg.voice, voice_id, text, out_audio, log=log)
    finally:
        client.close()


def render(cfg, audio, out_video, dry_run=False, log=print):
    """Returns (video_path_or_None, details_for_manifest)."""
    if cfg.backend == "heygen":
        client = heygen.HeyGen(api_key("HEYGEN_API_KEY", dry_run), cfg.heygen, dry_run, log=log)
        try:
            path, video_id = client.render(audio, out_video)
        finally:
            client.close()
        return path, {"backend": "heygen", "character_type": cfg.heygen.character_type,
                      "character_id": cfg.heygen.character_id, "video_id": video_id}
    path = local.render(cfg.local, cfg.paths.base_video, audio, out_video, dry_run, log)
    return path, {"backend": "local", "command": cfg.local.command[:1]}


def label(cfg, raw_video, final_video):
    if not cfg.output.label_enabled:
        raw_video.replace(final_video)
        return None
    media.burn_label(raw_video, final_video, cfg.output.label_text, cfg.output.font_file or None, {
        "comment": "Synthetically generated: {}".format(cfg.output.label_text),
        "description": "AI avatar video; likeness and voice used with the consent of the person depicted",
    })
    return cfg.output.label_text


def make(cfg, script_path, dry_run=False, log=print):
    media.require_ffmpeg()
    script_path = Path(script_path)
    text = script_path.read_text(encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = cfg.paths.output_dir / "{}_{}".format(script_path.stem, stamp)
    run_dir.mkdir(parents=True, exist_ok=True)

    audio = speak(cfg, text, run_dir / "voice.mp3", dry_run, log)
    raw_video, video_details = render(cfg, audio, run_dir / "render.mp4", dry_run, log)
    final, label_text = None, None
    if raw_video is not None:
        final = run_dir / "final.mp4"
        label_text = label(cfg, raw_video, final)

    manifest = {
        "created_utc": stamp,
        "dry_run": dry_run,
        "synthetic_media": True,
        "script": {"path": str(script_path), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                   "chars": len(text)},
        "voice": {"provider": "elevenlabs", "voice_id": cfg.voice.voice_id or load_state(cfg).get("voice_id"),
                  "model_id": cfg.voice.model_id},
        "video": video_details,
        "label": label_text,
        "files": {"audio": str(audio), "video": str(final) if final else None},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log("done: {}".format(final or run_dir))
    return manifest

# -*- coding: utf-8 -*-
"""Settings from a TOML file. API keys come only from the environment."""
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass
class Paths:
    voice_samples: Path = Path("data/voice_samples")
    voice_clean: Path = Path("data/voice_clean")
    photo: Path = Path("data/photo.jpg")
    base_video: Path = Path("data/base_footage.mp4")
    output_dir: Path = Path("output")


@dataclass
class VoiceConfig:
    base_url: str = "https://api.elevenlabs.io"
    voice_id: str = ""
    name: str = "My Voice"
    description: str = ""
    language: str = "en"
    remove_background_noise: bool = False
    model_id: str = "eleven_multilingual_v2"
    language_code: str = ""
    output_format: str = "mp3_44100_128"
    stability: float = 0.5
    similarity_boost: float = 0.8
    style: float = 0.0
    use_speaker_boost: bool = True
    speed: float = 1.0
    max_chunk_chars: int = 2500
    replacements: dict = field(default_factory=dict)


@dataclass
class HeyGenConfig:
    api_base: str = "https://api.heygen.com"
    upload_base: str = "https://upload.heygen.com"
    upload_path: str = "/v1/asset"
    generate_path: str = "/v2/video/generate"
    status_path: str = "/v1/video_status.get"
    character_type: str = "avatar"
    character_id: str = ""
    avatar_style: str = "normal"
    extra_character_fields: dict = field(default_factory=dict)
    width: int = 1280
    height: int = 720
    background_color: str = ""
    poll_interval_s: float = 15.0
    timeout_s: float = 3600.0


@dataclass
class LocalConfig:
    command: list = field(default_factory=list)
    workdir: str = ""
    fit_base_video: bool = True
    timeout_s: float = 7200.0


@dataclass
class OutputConfig:
    label_enabled: bool = True
    label_text: str = "AI-generated avatar"
    font_file: str = ""


@dataclass
class Config:
    root: Path
    paths: Paths
    voice: VoiceConfig
    backend: str
    heygen: HeyGenConfig
    local: LocalConfig
    output: OutputConfig


def _build(cls, raw, section):
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError("unknown key(s) in [{}]: {}".format(section, ", ".join(sorted(unknown))))
    return cls(**raw)


def load_config(path):
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError("config not found: {} (copy avatar.example.toml to start)".format(path))
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    root = path.parent

    paths = _build(Paths, raw.get("paths", {}), "paths")
    for f in fields(Paths):
        value = Path(getattr(paths, f.name)).expanduser()
        setattr(paths, f.name, value if value.is_absolute() else root / value)

    video = dict(raw.get("video", {}))
    heygen = _build(HeyGenConfig, video.pop("heygen", {}), "video.heygen")
    local = _build(LocalConfig, video.pop("local", {}), "video.local")
    backend = video.pop("backend", "heygen")
    if video:
        raise ConfigError("unknown key(s) in [video]: {}".format(", ".join(sorted(video))))
    if backend not in ("heygen", "local"):
        raise ConfigError("video.backend must be 'heygen' or 'local', got {!r}".format(backend))
    voice = _build(VoiceConfig, raw.get("voice", {}), "voice")
    if not voice.output_format.startswith("mp3_"):
        raise ConfigError("voice.output_format must be an mp3_* format (HeyGen accepts audio/mpeg only)")
    if heygen.character_type not in ("avatar", "talking_photo"):
        raise ConfigError("video.heygen.character_type must be 'avatar' or 'talking_photo'")

    return Config(
        root=root,
        paths=paths,
        voice=voice,
        backend=backend,
        heygen=heygen,
        local=local,
        output=_build(OutputConfig, raw.get("output", {}), "output"),
    )


def api_key(env_var, dry_run=False):
    key = os.environ.get(env_var, "").strip()
    if not key and not dry_run:
        raise ConfigError("set {} in the environment (never in the TOML file)".format(env_var))
    return key or "DRY-RUN"

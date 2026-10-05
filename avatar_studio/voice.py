# -*- coding: utf-8 -*-
"""ElevenLabs voice cloning (IVC) and chunked long-form text-to-speech.

Endpoints and field names match the official `elevenlabs` Python SDK
(v2.70.0): POST /v1/voices/add (multipart) and
POST /v1/text-to-speech/{voice_id} (JSON), authenticated with `xi-api-key`.
"""
import json
import mimetypes
import re
from pathlib import Path

import httpx

from . import media
from ._http import request_with_retry

AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}

# Sentence ends in Latin script plus the Devanagari danda / double danda.
_SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")


def chunk_text(text, max_chars):
    """Split text into <= max_chars chunks on paragraph, then sentence, then word boundaries."""
    chunks = []
    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        current = ""
        for sentence in _SENTENCE_END.split(" ".join(para.split())):
            pieces = [sentence]
            if len(sentence) > max_chars:
                pieces, word_run = [], ""
                for word in sentence.split(" "):
                    if word_run and len(word_run) + 1 + len(word) > max_chars:
                        pieces.append(word_run)
                        word_run = word
                    else:
                        word_run = "{} {}".format(word_run, word).strip()
                pieces.append(word_run)
            for piece in pieces:
                if current and len(current) + 1 + len(piece) > max_chars:
                    chunks.append(current)
                    current = piece
                else:
                    current = "{} {}".format(current, piece).strip()
        if current:
            chunks.append(current)
    return chunks


def apply_replacements(text, replacements):
    """Whole-word substitutions so jargon (S/4HANA, COBie, LOD) is pronounced right."""
    for term in sorted(replacements, key=len, reverse=True):
        text = re.sub(r"(?<!\w){}(?!\w)".format(re.escape(term)), replacements[term], text)
    return text


def estimate_seconds(text, words_per_minute=150):
    return max(1.0, len(text.split()) * 60.0 / words_per_minute)


class ElevenLabs:
    def __init__(self, api_key, base_url="https://api.elevenlabs.io", dry_run=False,
                 transport=None, timeout=180.0, log=print, sleep=None):
        self.dry_run = dry_run
        self.log = log
        self._retry_kwargs = {"sleep": sleep} if sleep else {}
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers={"xi-api-key": api_key},
            timeout=timeout, transport=transport,
        )

    def close(self):
        self._client.close()

    def create_ivc(self, name, sample_paths, description="", labels=None, remove_background_noise=False):
        data = {"name": name, "remove_background_noise": str(bool(remove_background_noise)).lower()}
        if description:
            data["description"] = description
        if labels:
            data["labels"] = json.dumps(labels)
        if self.dry_run:
            self.log("[dry-run] POST /v1/voices/add fields={} files={}".format(
                data, [Path(p).name for p in sample_paths]))
            return {"voice_id": "dry-run-voice", "requires_verification": False}
        # Read into memory so a retried request re-sends complete files.
        files = [
            ("files", (Path(p).name, Path(p).read_bytes(),
                       mimetypes.guess_type(str(p))[0] or "application/octet-stream"))
            for p in sample_paths
        ]
        response = request_with_retry(self._client, "POST", "/v1/voices/add", idempotent=False,
                                      data=data, files=files, **self._retry_kwargs)
        return response.json()

    def tts(self, voice_id, text, model_id, output_format="mp3_44100_128", language_code="",
            voice_settings=None, previous_text="", next_text=""):
        body = {"text": text, "model_id": model_id}
        if language_code:
            body["language_code"] = language_code
        if voice_settings:
            body["voice_settings"] = voice_settings
        if previous_text:
            body["previous_text"] = previous_text
        if next_text:
            body["next_text"] = next_text
        url = "/v1/text-to-speech/{}".format(voice_id)
        if self.dry_run:
            self.log("[dry-run] POST {}?output_format={} model={} chars={}".format(
                url, output_format, model_id, len(text)))
            return None
        response = request_with_retry(self._client, "POST", url, params={"output_format": output_format},
                                      json=body, **self._retry_kwargs)
        return response.content


def voice_settings(cfg):
    return {
        "stability": cfg.stability,
        "similarity_boost": cfg.similarity_boost,
        "style": cfg.style,
        "use_speaker_boost": cfg.use_speaker_boost,
        "speed": cfg.speed,
    }


def synthesize(client, cfg, voice_id, text, out_path, log=print):
    """Render a whole script to one MP3 at out_path, chunking for per-request limits."""
    out_path = Path(out_path)
    parts_dir = out_path.parent / (out_path.stem + "_parts")
    parts_dir.mkdir(parents=True, exist_ok=True)
    chunks = chunk_text(apply_replacements(text, cfg.replacements), cfg.max_chunk_chars)
    if not chunks:
        raise ValueError("script is empty")

    language_code = cfg.language_code
    if language_code and cfg.model_id.startswith("eleven_multilingual_v2"):
        log("note: language_code is not supported by {}; omitting it".format(cfg.model_id))
        language_code = ""
    # Request stitching (previous/next text) is used for the v2-family
    # models; eleven_v3 is sent each chunk on its own.
    stitch = not cfg.model_id.startswith("eleven_v3")

    parts = []
    for i, chunk in enumerate(chunks):
        part = parts_dir / "part_{:03d}.mp3".format(i)
        audio = client.tts(
            voice_id, chunk, cfg.model_id, cfg.output_format, language_code, voice_settings(cfg),
            previous_text=chunks[i - 1] if stitch and i > 0 else "",
            next_text=chunks[i + 1] if stitch and i + 1 < len(chunks) else "",
        )
        if audio is None:  # dry run: stand-in silence of realistic length
            media.silent_audio(part, estimate_seconds(chunk))
        else:
            part.write_bytes(audio)
        parts.append(part)
        log("tts {}/{} ({} chars) -> {}".format(i + 1, len(chunks), len(chunk), part.name))

    if len(parts) == 1:
        out_path.write_bytes(parts[0].read_bytes())
    else:
        media.concat_audio(parts, out_path)
    return out_path

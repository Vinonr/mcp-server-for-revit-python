# -*- coding: utf-8 -*-
"""HeyGen backend: lip-sync your cloned-voice audio onto your HeyGen avatar.

You create the avatar itself in HeyGen (Digital Twin from your own footage,
or Photo Avatar from a photo); HeyGen runs its own consent check for a real
person there. This module then uploads the audio as an asset and renders
video with the v2 generate/status endpoints. Paths live in config so a
HeyGen API revision is a config edit, not a code change.
"""
import time
from pathlib import Path

import httpx

from ._http import ApiError, request_with_retry

CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


class HeyGenError(RuntimeError):
    pass


def build_video_payload(cfg, audio_asset_id):
    if not cfg.character_id:
        raise HeyGenError("set video.heygen.character_id (your avatar_id or talking_photo_id)")
    if cfg.character_type == "avatar":
        character = {"type": "avatar", "avatar_id": cfg.character_id, "avatar_style": cfg.avatar_style}
    else:
        character = {"type": "talking_photo", "talking_photo_id": cfg.character_id}
    character.update(cfg.extra_character_fields)
    video_input = {"character": character, "voice": {"type": "audio", "audio_asset_id": audio_asset_id}}
    if cfg.background_color:
        video_input["background"] = {"type": "color", "value": cfg.background_color}
    return {"video_inputs": [video_input], "dimension": {"width": cfg.width, "height": cfg.height}}


def _data(response):
    body = response.json()
    if body.get("error"):
        raise HeyGenError("HeyGen error: {}".format(body["error"]))
    return body.get("data") or {}


class HeyGen:
    def __init__(self, api_key, cfg, dry_run=False, transport=None, timeout=300.0, log=print,
                 sleep=time.sleep, clock=time.monotonic):
        self.cfg = cfg
        self.dry_run = dry_run
        self.log = log
        self.sleep = sleep
        self.clock = clock
        self._client = httpx.Client(headers={"X-Api-Key": api_key, "Accept": "application/json"},
                                    timeout=timeout, transport=transport)
        # Rendered files sit on signed storage URLs: fetch them without the API key.
        self._storage = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)

    def close(self):
        self._client.close()
        self._storage.close()

    def upload_asset(self, path):
        path = Path(path)
        content_type = CONTENT_TYPES.get(path.suffix.lower())
        if content_type is None:
            raise HeyGenError("HeyGen accepts {} uploads, not {}".format(sorted(CONTENT_TYPES), path.suffix))
        url = self.cfg.upload_base.rstrip("/") + self.cfg.upload_path
        if self.dry_run:
            self.log("[dry-run] POST {} ({}, {} bytes)".format(url, content_type, path.stat().st_size))
            return {"id": "dry-run-asset"}
        response = request_with_retry(self._client, "POST", url, content=path.read_bytes(),
                                      headers={"Content-Type": content_type}, sleep=self.sleep)
        data = _data(response)
        if not data.get("id"):
            raise HeyGenError("upload returned no asset id: {}".format(response.text[:500]))
        return data

    def generate(self, payload):
        url = self.cfg.api_base.rstrip("/") + self.cfg.generate_path
        if self.dry_run:
            self.log("[dry-run] POST {} {}".format(url, payload))
            return "dry-run-video"
        response = request_with_retry(self._client, "POST", url, idempotent=False, json=payload,
                                      sleep=self.sleep)
        video_id = _data(response).get("video_id")
        if not video_id:
            raise HeyGenError("generate returned no video_id: {}".format(response.text[:500]))
        return video_id

    def wait(self, video_id):
        """Poll until completed; returns the status payload (contains video_url)."""
        url = self.cfg.api_base.rstrip("/") + self.cfg.status_path
        deadline = self.clock() + self.cfg.timeout_s
        last = None
        while True:
            response = request_with_retry(self._client, "GET", url, params={"video_id": video_id},
                                          sleep=self.sleep)
            data = _data(response)
            status = data.get("status")
            if status != last:
                self.log("heygen video {}: {}".format(video_id, status))
                last = status
            if status == "completed":
                return data
            if status == "failed":
                raise HeyGenError("render failed: {}".format(data.get("error")))
            if self.clock() >= deadline:
                raise HeyGenError("render still '{}' after {:.0f}s".format(status, self.cfg.timeout_s))
            self.sleep(self.cfg.poll_interval_s)

    def download(self, url, dst):
        dst = Path(dst)
        tmp = dst.with_suffix(dst.suffix + ".part")
        with self._storage.stream("GET", url) as response:
            if response.is_error:
                response.read()
                raise ApiError(response)
            with tmp.open("wb") as fh:
                for block in response.iter_bytes(1 << 20):
                    fh.write(block)
        tmp.replace(dst)
        return dst

    def render(self, audio_path, out_path):
        asset = self.upload_asset(audio_path)
        video_id = self.generate(build_video_payload(self.cfg, asset["id"]))
        if self.dry_run:
            return None, video_id
        status = self.wait(video_id)
        # Signed URLs expire (7 days at the time of writing): download now.
        return self.download(status["video_url"], out_path), video_id

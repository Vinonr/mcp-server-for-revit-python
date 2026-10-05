# -*- coding: utf-8 -*-
"""Tests for avatar_studio (no network; ffmpeg-backed tests skip without ffmpeg)."""
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from avatar_studio import capture, heygen, local, media, pipeline, voice
from avatar_studio._http import ApiError, request_with_retry
from avatar_studio.config import ConfigError, HeyGenConfig, VoiceConfig, load_config

EXAMPLE = Path(__file__).resolve().parents[2] / "avatar_studio" / "avatar.example.toml"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _no_sleep(_):
    pass


def _config(tmp_path, extra=""):
    path = tmp_path / "avatar.toml"
    path.write_text(EXAMPLE.read_text(encoding="utf-8") + extra, encoding="utf-8")
    return path


def _sine(path, seconds, rate=44100):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=220:sample_rate={}:duration={}".format(rate, seconds),
                    "-af", "volume=0.3", str(path)], check=True)
    return path


def _testsrc(path, seconds, size="320x240"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size={}:rate=25:duration={}".format(size, seconds),
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


class TestChunking:
    def test_respects_limit_and_keeps_every_word(self):
        text = " ".join("Sentence number {} is here.".format(i) for i in range(200))
        chunks = voice.chunk_text(text, 120)
        assert all(len(c) <= 120 for c in chunks)
        assert " ".join(chunks).split() == text.split()

    def test_splits_on_sentences_not_mid_sentence(self):
        chunks = voice.chunk_text("First one here. Second one here. Third.", 20)
        assert chunks == ["First one here.", "Second one here.", "Third."]

    def test_paragraphs_never_merge(self):
        assert voice.chunk_text("Para one.\n\nPara two.", 500) == ["Para one.", "Para two."]

    def test_danda_is_a_sentence_end(self):
        chunks = voice.chunk_text("नमस्ते। धन्यवाद।", 8)
        assert len(chunks) == 2

    def test_overlong_sentence_falls_back_to_words(self):
        chunks = voice.chunk_text("word " * 100, 50)
        assert all(len(c) <= 50 for c in chunks) and len(chunks) > 1


class TestReplacements:
    def test_whole_word_only(self):
        out = voice.apply_replacements("LOD 350 at the LODGE", {"LOD": "L O D"})
        assert out == "L O D 350 at the LODGE"

    def test_longest_term_wins(self):
        out = voice.apply_replacements("SAP S/4HANA", {"S/4HANA": "S 4 HANA", "SAP": "sap"})
        assert out == "sap S 4 HANA"


class TestConfig:
    def test_example_loads_and_resolves_paths(self, tmp_path):
        cfg = load_config(_config(tmp_path))
        assert cfg.backend == "heygen"
        assert cfg.paths.output_dir == tmp_path / "output"
        assert cfg.voice.replacements["S/4HANA"] == "S 4 HANA"
        assert "{audio}" in cfg.local.command

    def test_unknown_key_rejected(self, tmp_path):
        path = tmp_path / "a.toml"
        path.write_text('[voice]\nmodel = "x"\n', encoding="utf-8")
        with pytest.raises(ConfigError, match="model"):
            load_config(path)

    def test_non_mp3_output_rejected(self, tmp_path):
        path = tmp_path / "a.toml"
        path.write_text('[voice]\noutput_format = "pcm_44100"\n', encoding="utf-8")
        with pytest.raises(ConfigError, match="mp3"):
            load_config(path)

    def test_bad_backend_rejected(self, tmp_path):
        path = tmp_path / "a.toml"
        path.write_text('[video]\nbackend = "cloud"\n', encoding="utf-8")
        with pytest.raises(ConfigError, match="backend"):
            load_config(path)


class TestRetry:
    def _client(self, statuses):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(statuses[min(len(calls), len(statuses)) - 1], text="x")
        return httpx.Client(transport=httpx.MockTransport(handler)), calls

    def test_idempotent_retries_5xx(self):
        client, calls = self._client([500, 200])
        assert request_with_retry(client, "GET", "https://x/y", sleep=_no_sleep).status_code == 200
        assert len(calls) == 2

    def test_create_does_not_retry_5xx(self):
        client, calls = self._client([500, 200])
        with pytest.raises(ApiError):
            request_with_retry(client, "POST", "https://x/y", idempotent=False, sleep=_no_sleep)
        assert len(calls) == 1

    def test_create_retries_429(self):
        client, calls = self._client([429, 200])
        request_with_retry(client, "POST", "https://x/y", idempotent=False, sleep=_no_sleep)
        assert len(calls) == 2


class TestElevenLabs:
    def test_ivc_request_shape(self, tmp_path):
        sample = tmp_path / "s1.wav"
        sample.write_bytes(b"RIFFdata")
        seen = {}

        def handler(request):
            seen["request"] = request
            return httpx.Response(200, json={"voice_id": "v123", "requires_verification": False})
        client = voice.ElevenLabs("k", transport=httpx.MockTransport(handler))
        result = client.create_ivc("Me", [sample], labels={"language": "en"})
        req = seen["request"]
        body = req.read()
        assert result["voice_id"] == "v123"
        assert req.url.path == "/v1/voices/add" and req.headers["xi-api-key"] == "k"
        assert b'name="files"; filename="s1.wav"' in body and b'name="name"' in body
        assert b'{"language": "en"}' in body

    @needs_ffmpeg
    def test_synthesize_stitches_chunks(self, tmp_path):
        mp3 = media.silent_audio(tmp_path / "chunk.mp3", 1.0).read_bytes()
        bodies = []

        def handler(request):
            assert request.url.params["output_format"] == "mp3_44100_128"
            bodies.append(json.loads(request.content))
            return httpx.Response(200, content=mp3)
        cfg = VoiceConfig(max_chunk_chars=20, language_code="ta")
        client = voice.ElevenLabs("k", transport=httpx.MockTransport(handler))
        out = voice.synthesize(client, cfg, "v1", "One two three. Four five six. Seven.",
                               tmp_path / "out.mp3", log=_no_sleep)
        assert len(bodies) == 3
        assert "previous_text" not in bodies[0] and bodies[1]["previous_text"] == bodies[0]["text"]
        assert bodies[1]["next_text"] == bodies[2]["text"]
        assert all("language_code" not in b for b in bodies)  # unsupported on multilingual_v2
        assert media.probe(out).duration == pytest.approx(3.0, abs=0.3)

    @needs_ffmpeg
    def test_v3_sends_language_code_without_stitching(self, tmp_path):
        mp3 = media.silent_audio(tmp_path / "chunk.mp3", 0.5).read_bytes()
        bodies = []

        def handler(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, content=mp3)
        cfg = VoiceConfig(model_id="eleven_v3", max_chunk_chars=10, language_code="ml")
        client = voice.ElevenLabs("k", transport=httpx.MockTransport(handler))
        voice.synthesize(client, cfg, "v1", "Alpha one. Beta two.", tmp_path / "o.mp3", log=_no_sleep)
        assert all(b["language_code"] == "ml" and "previous_text" not in b for b in bodies)


class TestHeyGen:
    def test_payload_avatar(self):
        cfg = HeyGenConfig(character_id="a1", background_color="#fff")
        payload = heygen.build_video_payload(cfg, "asset9")
        assert payload["video_inputs"][0]["character"] == {"type": "avatar", "avatar_id": "a1", "avatar_style": "normal"}
        assert payload["video_inputs"][0]["voice"] == {"type": "audio", "audio_asset_id": "asset9"}
        assert payload["video_inputs"][0]["background"] == {"type": "color", "value": "#fff"}
        assert payload["dimension"] == {"width": 1280, "height": 720}

    def test_payload_talking_photo_with_extra_fields(self):
        cfg = HeyGenConfig(character_type="talking_photo", character_id="p1",
                           extra_character_fields={"use_avatar_iv_model": True})
        character = heygen.build_video_payload(cfg, "a")["video_inputs"][0]["character"]
        assert character == {"type": "talking_photo", "talking_photo_id": "p1", "use_avatar_iv_model": True}

    def test_payload_requires_character(self):
        with pytest.raises(heygen.HeyGenError):
            heygen.build_video_payload(HeyGenConfig(), "a")

    def _flow(self, statuses):
        requests = []
        status_iter = iter(statuses)

        def handler(request):
            requests.append(request)
            if request.url.host == "upload.heygen.com":
                return httpx.Response(200, json={"code": 100, "data": {"id": "asset1"}})
            if request.url.path == "/v2/video/generate":
                return httpx.Response(200, json={"error": None, "data": {"video_id": "vid1"}})
            if request.url.path == "/v1/video_status.get":
                return httpx.Response(200, json={"data": next(status_iter)})
            if request.url.host == "files.example.com":
                return httpx.Response(200, content=b"MP4DATA")
            return httpx.Response(404)
        return requests, httpx.MockTransport(handler)

    def test_render_end_to_end(self, tmp_path):
        audio = tmp_path / "v.mp3"
        audio.write_bytes(b"ID3")
        requests, transport = self._flow([
            {"status": "processing"},
            {"status": "completed", "video_url": "https://files.example.com/v.mp4?sig=1"},
        ])
        client = heygen.HeyGen("secret", HeyGenConfig(character_id="a1"), transport=transport,
                               log=_no_sleep, sleep=_no_sleep)
        path, video_id = client.render(audio, tmp_path / "r.mp4")
        assert video_id == "vid1" and path.read_bytes() == b"MP4DATA"
        upload, generate = requests[0], requests[1]
        assert upload.headers["content-type"] == "audio/mpeg" and upload.content == b"ID3"
        assert json.loads(generate.content)["video_inputs"][0]["voice"]["audio_asset_id"] == "asset1"
        assert "x-api-key" not in requests[-1].headers  # key never sent to storage host

    def test_failed_render_raises(self, tmp_path):
        _, transport = self._flow([{"status": "failed", "error": {"message": "bad audio"}}])
        client = heygen.HeyGen("k", HeyGenConfig(), transport=transport, log=_no_sleep, sleep=_no_sleep)
        with pytest.raises(heygen.HeyGenError, match="bad audio"):
            client.wait("vid1")

    def test_timeout_raises(self):
        _, transport = self._flow([{"status": "processing"}] * 10)
        ticks = iter(range(0, 10000, 1000))
        client = heygen.HeyGen("k", HeyGenConfig(timeout_s=2500), transport=transport, log=_no_sleep,
                               sleep=_no_sleep, clock=lambda: next(ticks))
        with pytest.raises(heygen.HeyGenError, match="processing"):
            client.wait("vid1")

    def test_rejects_wav_upload(self, tmp_path):
        wav = tmp_path / "a.wav"
        wav.write_bytes(b"x")
        with pytest.raises(heygen.HeyGenError):
            heygen.HeyGen("k", HeyGenConfig(), log=_no_sleep).upload_asset(wav)


class TestLocal:
    def test_build_command_substitutes(self, tmp_path):
        cmd = local.build_command(["run", "--a={audio}", "{video}", "{output}"], tmp_path / "v.mp4",
                                  tmp_path / "a.mp3", tmp_path / "o.mp4")
        assert cmd == ["run", "--a=" + str(tmp_path / "a.mp3"), str(tmp_path / "v.mp4"), str(tmp_path / "o.mp4")]

    def test_template_must_take_audio(self, tmp_path):
        with pytest.raises(local.LocalBackendError):
            local.build_command(["run", "{video}", "{output}"], "v", "a", "o")


@needs_ffmpeg
class TestMedia:
    def test_pingpong_extends_short_footage(self, tmp_path):
        src = _testsrc(tmp_path / "src.mp4", 3)
        out = media.fit_video_to_duration(src, 7.5, tmp_path / "fit.mp4", segment_s=1.0)
        info = media.probe(out)
        assert info.duration == pytest.approx(7.5, abs=0.15) and not info.has_audio

    def test_long_footage_is_trimmed(self, tmp_path):
        src = _testsrc(tmp_path / "src.mp4", 4)
        out = media.fit_video_to_duration(src, 2.0, tmp_path / "fit.mp4")
        assert media.probe(out).duration == pytest.approx(2.0, abs=0.1)

    def test_clean_voice_sample_is_mono_44k(self, tmp_path):
        src = _sine(tmp_path / "raw.wav", 3, rate=48000)
        info = media.probe(media.clean_voice_sample(src, tmp_path / "clean" / "raw.wav"))
        assert (info.sample_rate, info.channels) == (44100, 1)


@needs_ffmpeg
class TestCapture:
    def test_too_little_audio_is_an_error(self, tmp_path):
        _sine(tmp_path / "a.wav", 5)
        findings = capture.check_voice_samples(tmp_path)
        assert any(f.level == "error" and "60s" in f.message for f in findings)
        assert any(f.level == "warn" and "30-120s" in f.message for f in findings)

    def test_low_res_footage_is_an_error(self, tmp_path):
        findings = capture.check_footage(_testsrc(tmp_path / "f.mp4", 10))
        assert any(f.level == "error" and "1080p" in f.message for f in findings)


@needs_ffmpeg
class TestPipeline:
    def test_dry_run_make_writes_manifest(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        cfg = load_config(_config(tmp_path))
        cfg.heygen.character_id = "avatar-1"
        script = tmp_path / "pitch.txt"
        script.write_text("We deliver LOD 400 precast models. Synced to SAP S/4HANA.", encoding="utf-8")
        manifest = pipeline.make(cfg, script, dry_run=True, log=_no_sleep)
        assert manifest["dry_run"] and manifest["synthetic_media"]
        assert manifest["video"]["video_id"] == "dry-run-video" and manifest["files"]["video"] is None
        assert Path(manifest["files"]["audio"]).exists()

    def test_local_render_then_label(self, tmp_path):
        cfg = load_config(_config(tmp_path))
        cfg.local.command = ["ffmpeg", "-y", "-loglevel", "error", "-i", "{video}", "-i", "{audio}",
                             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", "{output}"]
        base = _testsrc(tmp_path / "base.mp4", 2)
        audio = media.silent_audio(tmp_path / "voice.mp3", 4.0)
        raw = local.render(cfg.local, base, audio, tmp_path / "render.mp4", log=_no_sleep)
        final = tmp_path / "final.mp4"
        assert pipeline.label(cfg, raw, final) == "AI-generated avatar"
        info = media.probe(final)
        assert info.has_video and info.has_audio and info.duration == pytest.approx(4.0, abs=0.3)
        tags = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(final)],
                                         capture_output=True, text=True, check=True).stdout)["format"]["tags"]
        assert "Synthetically generated" in tags["comment"]

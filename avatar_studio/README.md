# avatar_studio: a talking digital twin with your face, body and voice

Type a script and get back an MP4 of **you** delivering it, in your own
cloned voice, with an AI-disclosure label and a provenance manifest.

```
 your recordings                     avatar_studio                         output/<script>_<UTC>/
 ───────────────                     ─────────────                         ──────────────────────
 voice takes ──► check ──► prep-voice ──► clone-voice ─┐                    voice.mp3
                                         (ElevenLabs)   ├─► speak ─► render ─► label ─► final.mp4
 script.txt ────────────────────────────────────────────┘    │                          manifest.json
                                                              ├─ heygen: your Digital Twin / Photo Avatar
 footage ──► HeyGen Digital Twin  (hosted)  ─────────────────┤
         └─► data/base_footage.mp4 (local GPU lip-sync) ─────┘
```

## Pick a path

| | **Hosted** (`backend = "heygen"`) | **Self-hosted** (`backend = "local"`) |
|---|---|---|
| Voice | ElevenLabs Instant Voice Clone | ElevenLabs Instant Voice Clone |
| Face + body | HeyGen Digital Twin, trained on 2–5 min of your footage (or a Photo Avatar) | Your 30–60 s base footage, re-lip-synced by LatentSync / MuseTalk / any v2v model |
| Where your face goes | HeyGen | Stays on your machine |
| Hardware | None | NVIDIA GPU (check the model's VRAM requirement) |
| Realism | Highest (body motion follows speech) | Good mouth; body loops, so gestures don't track the words |
| Time to first video | Same day | 1–2 days of model setup |

Start hosted. Move to self-hosted if your face data must stay on-premises.

## Phases

| # | Phase | Input | Command / action | Output |
|---|---|---|---|---|
| 0 | Setup | – | Install `ffmpeg`. `httpx` already comes with this repo's dependencies. Copy `avatar.example.toml` to `avatar.toml`. Export `ELEVENLABS_API_KEY` and `HEYGEN_API_KEY`. | config |
| 1 | Capture | You | Follow [RECORDING_GUIDE.md](RECORDING_GUIDE.md) | `data/voice_samples/*.wav`, footage |
| 2 | Validate | recordings | `check` | pass/fail report (exit 1 on errors) |
| 3 | Clean voice | raw takes | `prep-voice` | `data/voice_clean/*.wav` (mono 44.1 kHz, silence-trimmed, −18 LUFS) |
| 4 | Clone voice | clean takes | `clone-voice` | `voice_id` in `output/state.json` |
| 5 | Build the face/body avatar | footage | **Hosted:** create a Digital Twin in the HeyGen web app (it records your consent video), then paste the ID into `character_id`. **Local:** set `[video.local]` and `paths.base_video`. | avatar ID / model command |
| 6 | Dry run | script | `--dry-run make script.txt` | request payloads printed, no billing |
| 7 | Produce | script | `make script.txt` | `voice.mp3`, `render.mp4`, `final.mp4`, `manifest.json` |

Run from the repo root. Paths in the config resolve next to the config file,
so recordings and renders land in `avatar_studio/data/` and `avatar_studio/output/`,
which are git-ignored along with `avatar.toml`.

```bash
cp avatar_studio/avatar.example.toml avatar_studio/avatar.toml
export ELEVENLABS_API_KEY=... HEYGEN_API_KEY=...
alias avatar="python -m avatar_studio --config avatar_studio/avatar.toml"

avatar check
avatar prep-voice
avatar clone-voice
avatar --dry-run make scripts/intro.txt
avatar make scripts/intro.txt
```

The other commands are `speak script.txt` (audio only) and `render voice.mp3`
(re-render an existing take with a different avatar or backend).

## Languages and pronunciation

- `eleven_multilingual_v2` (the default) is the steadiest model for long-form English, Hindi or Tamil narration.
- Switch to `eleven_v3` for Malayalam, Telugu or Kannada, or for expressive delivery. v3 accepts inline tags such as `[excited]` and `[pause]`. Set `language_code` (e.g. `ml`) to pin the language; v2 ignores it.
- One clone speaks every supported language with your accent. A native-language take in your samples makes that accent sound right.
- `[voice.replacements]` rewrites jargon before TTS (`S/4HANA` → `S 4 HANA`, `LOD` → `L O D`). Add your project and client names.

## Risks and limits

- **HeyGen API version.** The HeyGen calls use the v1 asset upload and the v2 `video/generate` and `video_status.get` endpoints, as HeyGen documented them through late 2025. HeyGen now also documents a v3 API, which could not be checked from the environment this was built in. The endpoint paths and extra character fields are config values (`[video.heygen]`). Before the first real render, run `--dry-run`, then render a 10-second test script.
- **ElevenLabs** endpoints and fields match the official Python SDK v2.70.0.
- **Billing safety.** Calls that create a billable object (a voice clone, a video render) are retried only on HTTP 429. They are never retried on 5xx or a dropped connection, because the server may already have done the work and a retry could create a duplicate. TTS, uploads and polling retry with backoff.
- **Your biometric data.** Under the DPDP Act 2023, your voice and face are personal data. In hosted mode, ElevenLabs and HeyGen process them, so review each vendor's data processing agreement and retention terms. ElevenLabs offers an India data-residency endpoint (see `base_url`) for residency-enabled workspaces. Zero-retention mode is enterprise-only and is not wired in.
- **Disclosure.** Under the IT Rules amendment in force since 20 Feb 2026, synthetic audio and video must carry a prominent label and provenance metadata. `final.mp4` gets a burned-in label plus MP4 `comment`/`description` tags. Those tags are easy to strip; they are **not** C2PA. For tamper-evident provenance, sign outputs with C2PA (e.g. `c2patool`) as a next step. LinkedIn and YouTube also ask you to declare AI content when you upload.
- **Impersonation.** Anyone holding your API key and `voice_id` can make "you" say anything. Use scoped keys with credit limits where your plan offers them, rotate them, and never commit `avatar.toml`, `state.json` or recordings (all are git-ignored). Agree a verbal code word with your family and finance team for voice or video requests that move money.
- **Quality ceiling.** An instant clone is close but not identical; Professional Voice Cloning (30+ min of audio) is closer. HeyGen's video URLs expire, so the tool downloads the render immediately.

## Tests

```bash
python -m pytest tests/unit/test_avatar_studio.py -q   # no network; ffmpeg-backed tests skip without ffmpeg
```

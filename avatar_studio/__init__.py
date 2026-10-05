# -*- coding: utf-8 -*-
"""avatar_studio: build a talking digital twin from your own face, body and voice.

Pipeline: voice samples -> voice clone (ElevenLabs IVC) -> script TTS ->
lip-synced video (HeyGen hosted avatar, or a self-hosted open-source
lip-sync model) -> AI-disclosure label -> MP4 + provenance manifest.
"""

__version__ = "0.1.0"

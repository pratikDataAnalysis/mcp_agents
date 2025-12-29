"""
Audio domain package.

This centralizes:
- inbound media parsing (Twilio metadata -> audio item)
- Twilio voice-note transcription (media_url -> text)

Older locations (under `src/app/api/twilio/`) were kept as thin wrappers during migration,
but are now removed; import from `src.app.audio.*` directly.
"""

from __future__ import annotations

from src.app.audio.media import TwilioMediaItem, pick_first_audio_media
from src.app.audio.twilio_stt import transcribe_twilio_audio

__all__ = [
    "TwilioMediaItem",
    "pick_first_audio_media",
    "transcribe_twilio_audio",
]



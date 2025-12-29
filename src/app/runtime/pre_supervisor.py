"""
Pre-supervisor preprocessing (worker-side).

Why this exists:
- Keep `RedisStreamWorker._process_message` small and readable.
- Centralize media/STT + language detection + envelope construction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.app.audio import pick_first_audio_media, transcribe_twilio_audio
from src.app.config.settings import settings
from src.app.mcp.tools.language_tools import localAudio_detect_and_translate_to_english


@dataclass(frozen=True)
class PreSupervisorResult:
    supervisor_input: str
    original_text: str
    english_text: str
    detected_language: str
    is_english: bool
    inbound_has_audio: bool
    # If set, caller should skip supervisor and reply immediately.
    immediate_reply: Optional[str] = None


async def _detect_language_and_english_text(text: str) -> tuple[str, str, bool]:
    payload = await localAudio_detect_and_translate_to_english.ainvoke({"text": text})
    if isinstance(payload, dict):
        detected = (payload.get("detected_language") or "").strip()
        english = (payload.get("english_text") or "").strip()
        dl = detected.lower()
        is_english = dl in {"english", "en", "en-us", "en-gb"}
        return detected, english, is_english
    return "English", text, True


def _build_supervisor_envelope(
    *,
    ctx: Any,
    original_text: str,
    english_text: str,
    detected_language: str,
    is_english: bool,
    inbound_has_audio: bool,
) -> str:
    envelope = {
        "schema": "inbound_envelope_v1",
        "source": getattr(ctx, "source", "unknown"),
        "user_id": getattr(ctx, "user_id", "unknown"),
        "message_id": getattr(ctx, "message_id", ""),
        "conversation_id": getattr(ctx, "conversation_id", ""),
        "stream_message_id": getattr(ctx, "stream_message_id", ""),
        "timestamp": getattr(ctx, "timestamp", None),
        "original_text": original_text,
        "english_text": english_text,
        "detected_language": detected_language,
        "is_english": is_english,
        "requires_translation_to_english": (not is_english),
        "inbound_has_audio": inbound_has_audio,
        "reply_in_audio": inbound_has_audio,
    }
    return "INPUT_ENVELOPE_JSON:\n" + json.dumps(envelope, ensure_ascii=False) + "\n"


async def prepare_for_supervisor(*, ctx: Any, metadata: Dict[str, Any]) -> PreSupervisorResult:
    """
    Normalize inbound message into a supervisor-ready input envelope.
    """
    inbound_has_audio = bool(pick_first_audio_media(metadata))

    text = (getattr(ctx, "text", "") or "").strip()
    if not text and inbound_has_audio:
        audio = pick_first_audio_media(metadata)
        if audio:
            transcript, _debug_dir = await transcribe_twilio_audio(
                media_url=audio.url,
                content_type=audio.content_type,
                twilio_account_sid=settings.twilio_account_sid or "",
                twilio_auth_token=settings.twilio_auth_token or "",
                openai_api_key=settings.openai_api_key or "",
                model="whisper-1",
                # Prefer original-language transcript; downstream handles translation.
                force_english=False,
            )
            text = (transcript or "").strip()

    if not text:
        return PreSupervisorResult(
            supervisor_input="",
            original_text="",
            english_text="",
            detected_language="",
            is_english=True,
            inbound_has_audio=inbound_has_audio,
            immediate_reply="Send a message and I’ll help.",
        )

    detected_lang, english_text, is_english = await _detect_language_and_english_text(text)
    english_text = (english_text or text).strip()

    supervisor_input = _build_supervisor_envelope(
        ctx=ctx,
        original_text=text,
        english_text=english_text,
        detected_language=detected_lang,
        is_english=is_english,
        inbound_has_audio=inbound_has_audio,
    )

    return PreSupervisorResult(
        supervisor_input=supervisor_input,
        original_text=text,
        english_text=english_text,
        detected_language=detected_lang,
        is_english=is_english,
        inbound_has_audio=inbound_has_audio,
        immediate_reply=None,
    )



"""
Twilio inbound media helpers (WhatsApp, MMS, etc.).

Purpose:
- Keep "is this an audio/media message?" detection logic out of the FastAPI webhook.
- Provide a stable metadata contract we can publish to Redis and later interpret in workers.

Twilio sends media fields in form-encoded payloads:
- NumMedia: "0" | "1" | ...
- MediaUrl0, MediaContentType0
- MediaUrl1, MediaContentType1, ...
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class TwilioMediaItem:
    url: str
    content_type: str

    @property
    def is_audio(self) -> bool:
        return (self.content_type or "").lower().startswith("audio/")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def extract_media_items_from_form(form: Mapping[str, Any]) -> List[TwilioMediaItem]:
    """
    Extract media items from a Twilio webhook form payload.
    """
    n = _safe_int(form.get("NumMedia"), 0)
    items: List[TwilioMediaItem] = []
    for i in range(max(n, 0)):
        url = (form.get(f"MediaUrl{i}") or "").strip()
        ctype = (form.get(f"MediaContentType{i}") or "").strip()
        if url and ctype:
            items.append(TwilioMediaItem(url=url, content_type=ctype))
    return items


def build_media_metadata_from_form(form: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Build a Redis-safe metadata dict from Twilio form payload.

    This is intentionally small and explicit so it survives JSON serialization.
    """
    items = extract_media_items_from_form(form)
    return {
        "num_media": len(items),
        "media": [{"url": i.url, "content_type": i.content_type} for i in items],
    }


def pick_first_audio_media(metadata: Mapping[str, Any]) -> Optional[TwilioMediaItem]:
    """
    Given decoded metadata (dict), return the first audio media item if present.
    """
    media = metadata.get("media") or []
    if not isinstance(media, list):
        return None
    for item in media:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        ctype = (item.get("content_type") or "").strip()
        if not url or not ctype:
            continue
        tm = TwilioMediaItem(url=url, content_type=ctype)
        if tm.is_audio:
            return tm
    return None


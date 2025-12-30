"""
Twilio inbound media helpers (WhatsApp, MMS, etc.).

Purpose:
- Keep "is this an audio/media message?" detection logic out of the FastAPI webhook/worker.
- Provide a stable metadata contract we can publish to Redis and later interpret in workers.

Also:
- Provide small, reusable helpers for outbound media handling (e.g., TTS file hosting).
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from src.app.config.settings import settings


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


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def guess_mime_type_from_audio_format(fmt: str) -> str:
    fmt_l = (fmt or "").lower().strip()
    if fmt_l == "mp3":
        return "audio/mpeg"
    if fmt_l == "wav":
        return "audio/wav"
    if fmt_l == "ogg":
        return "audio/ogg"
    if fmt_l == "m4a":
        return "audio/mp4"
    return "application/octet-stream"


def build_public_media_url(*, rel_path: str) -> Optional[str]:
    """
    Build a publicly reachable URL for a file served by the ingress media route:
      GET /media/{rel_path:path}
    """
    base = (settings.media_public_base_url or settings.base_url or "").strip().rstrip("/")
    if not base:
        return None
    rel = rel_path.lstrip("/")
    return f"{base}/media/{rel}"


def build_media_root_path(*, rel_path: str) -> str:
    """
    Convert a relative path under the media root (e.g., 'tts/abc.mp3')
    into an absolute filesystem path rooted at settings.media_root_dir.
    """
    rel = rel_path.lstrip("/")
    root = Path(settings.media_root_dir)
    return str(root / rel)


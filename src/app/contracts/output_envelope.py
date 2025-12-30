"""
OutputEnvelope contract (Phase 3).

This is the normalized output payload produced by the execution runtime (worker),
and published to an outbound Redis Stream for delivery by a dispatcher.

All values are designed to be string-safe for Redis Streams (decode_responses=True).
Any structured fields must be JSON-encoded strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OutputEnvelope:
    out_id: str
    correlation_id: str
    conversation_id: str
    source: str
    user_id: str
    reply_text: str
    # Optional media reply (e.g., WhatsApp voice note reply)
    reply_audio_url: Optional[str] = None
    reply_audio_mime_type: Optional[str] = None
    status: str  # "success" | "error"
    timestamp: str  # UTC ISO string
    metadata: Optional[str] = None  # JSON string

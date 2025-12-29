"""
Structured response contract for Supervisor output.

Why this exists:
- Ensures the final reply returned by Supervisor is deterministic and machine-parseable.
- Avoids leaking internal routing messages (e.g., "Transferring back to supervisor").
- Provides a stable contract for outbound delivery layers (WhatsApp today, others later).
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class SupervisorStructuredReply(BaseModel):
    """
    Final user-facing reply contract emitted by Supervisor.

    This object is generated via model.with_structured_output() through
    langgraph-supervisor's response_format feature.

    Notes:
    - reply_text must always be safe to send directly to the user.
    - status + error_message help downstream systems handle failures consistently.
    """

    reply_text: str = Field(..., min_length=1, description="User-facing reply text.")
    status: Literal["success", "error"] = Field(
        "success", description="Whether the request succeeded."
    )
    actions: List[str] = Field(
        default_factory=list,
        description="Optional list of actions performed (for observability).",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="If status=error, a short user-safe error message.",
    )

    # Optional TTS artifact fields (Phase: audio reply generation)
    tts_file_path: Optional[str] = Field(
        default=None,
        description="If an audio reply was generated, local file path to the synthesized audio.",
    )
    tts_format: Optional[str] = Field(
        default=None,
        description="Audio format for tts_file_path (e.g., mp3).",
    )

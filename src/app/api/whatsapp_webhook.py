"""
WhatsApp webhook (Twilio).

Responsibilities:
- Receive inbound WhatsApp messages from Twilio
- Normalize message payload
- Publish message to Redis Stream
- Respond immediately to Twilio

NOTE:
- No agent logic
- No Supervisor calls
- No Redis consumption
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from typing import Any

from src.app.logging.logger import setup_logger
from src.app.infra.redis import RedisClient, RedisStreamPublisher
from src.app.config.settings import settings
from src.app.audio.media import build_media_metadata_from_form

logger = setup_logger(__name__)

router = APIRouter()


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    """
    Twilio WhatsApp webhook entrypoint.
    """
    form = await request.form()
    form_data = dict(form)

    # Twilio standard fields
    user_id = (form_data.get("From") or "").strip()
    text = (form_data.get("Body") or "").strip()
    message_sid = (form_data.get("MessageSid") or "").strip()
    media_meta = build_media_metadata_from_form(form_data)
    has_media = bool(media_meta.get("num_media"))

    if not user_id or (not text and not has_media):
        logger.warning("Invalid WhatsApp payload received | form=%s", form_data)
        return Response(status_code=400)

    logger.info(
        "WhatsApp message received | user_id=%s | message_sid=%s | has_media=%s",
        user_id,
        message_sid,
        has_media,
    )

    # Initialize Redis publisher
    redis_client = RedisClient()
    publisher = RedisStreamPublisher(
        redis_client=redis_client,
        stream_name=settings.redis_stream_inbound,
    )

    # Publish message to Redis Stream
    stream_id = await publisher.publish_message(
        source="whatsapp",
        user_id=user_id,
        # For media-only messages, text may be empty. Worker will STT audio.
        text=text,
        metadata={
            "message_sid": message_sid,
            **media_meta,
        },
    )

    logger.info(
        "WhatsApp message published to Redis | stream_id=%s | user_id=%s",
        stream_id,
        user_id,
    )

    # Respond immediately to Twilio
    return Response(status_code=200)

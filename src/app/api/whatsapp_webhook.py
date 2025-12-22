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
from src.app.infra.redis_client import RedisClient
from src.app.infra.redis_stream_publisher import RedisStreamPublisher
from src.app.config.settings import settings

logger = setup_logger(__name__)

router = APIRouter()


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    """
    Twilio WhatsApp webhook entrypoint.
    """
    form = await request.form()

    # Twilio standard fields
    user_id = form.get("From", "")
    text = form.get("Body", "")
    message_sid = form.get("MessageSid", "")

    if not user_id or not text:
        logger.warning("Invalid WhatsApp payload received | form=%s", dict(form))
        return Response(status_code=400)

    logger.info(
        "WhatsApp message received | user_id=%s | message_sid=%s",
        user_id,
        message_sid,
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
        text=text,
        metadata={
            "message_sid": message_sid,
        },
    )

    logger.info(
        "WhatsApp message published to Redis | stream_id=%s | user_id=%s",
        stream_id,
        user_id,
    )

    # Respond immediately to Twilio
    return Response(status_code=200)

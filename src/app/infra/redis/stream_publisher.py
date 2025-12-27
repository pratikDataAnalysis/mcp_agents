"""
Redis Stream publisher (inbound).

Responsibilities:
- Publish inbound user messages to a Redis Stream
- Enforce a normalized message schema
- Log publish lifecycle clearly

NOTE:
- This module does NOT process messages.
- It only appends events to a Redis Stream.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict

from src.app.infra.redis.client import RedisClient
from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


class RedisStreamPublisher:
    """
    Publishes messages to a Redis Stream.
    """

    def __init__(self, redis_client: RedisClient, stream_name: str) -> None:
        self.redis_client = redis_client
        self.stream_name = stream_name

    async def publish_message(
        self,
        *,
        source: str,
        user_id: str,
        text: str,
        conversation_id: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> str:
        """
        Publish a normalized inbound message to Redis Stream.

        Returns:
            stream_id (str): Redis-generated stream entry ID
        """
        client = await self.redis_client.get_client()

        message_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()

        payload: Dict[str, str] = {
            "message_id": message_id,
            "source": source,
            "user_id": user_id,
            "conversation_id": conversation_id or message_id,
            "text": text,
            "timestamp": timestamp,
        }

        if metadata:
            # Store metadata as JSON string (stable, parseable)
            payload["metadata"] = json.dumps(metadata)

        logger.info(
            "Publishing message to Redis Stream | stream=%s | message_id=%s | source=%s",
            self.stream_name,
            message_id,
            source,
        )

        try:
            stream_id = await client.xadd(
                name=self.stream_name,
                fields=payload,
            )
        except Exception as exc:
            logger.error("Failed to publish message to Redis Stream", exc_info=exc)
            raise

        logger.debug(
            "Message published | stream=%s | stream_id=%s | payload_keys=%s",
            self.stream_name,
            stream_id,
            list(payload.keys()),
        )

        return stream_id


"""
Redis Stream outbound publisher.

Responsibilities:
- Publish execution outputs (OutputEnvelope) to an outbound Redis Stream
- Log publish lifecycle clearly

NOTE:
- This module does NOT deliver messages to WhatsApp/Twilio.
- It only appends outbound events to Redis.
"""

from __future__ import annotations

from typing import Dict

from src.app.infra.redis_client import RedisClient
from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


class RedisStreamOutboundPublisher:
    def __init__(self, redis_client: RedisClient, stream_name: str) -> None:
        self.redis_client = redis_client
        self.stream_name = stream_name

    async def publish_output(self, payload: Dict[str, str]) -> str:
        """
        Publish an outbound payload to the outbound Redis Stream.

        Returns:
            stream_id (str): Redis-generated stream entry ID
        """
        client = await self.redis_client.get_client()

        logger.info(
            "Publishing outbound message | stream=%s | correlation_id=%s | user_id=%s",
            self.stream_name,
            payload.get("correlation_id", "unknown"),
            payload.get("user_id", "unknown"),
        )

        try:
            stream_id = await client.xadd(
                name=self.stream_name,
                fields=payload,
            )
        except Exception as exc:
            logger.error("Failed to publish outbound message", exc_info=exc)
            raise

        logger.debug(
            "Outbound message published | stream=%s | stream_id=%s | payload_keys=%s",
            self.stream_name,
            stream_id,
            list(payload.keys()),
        )

        return stream_id

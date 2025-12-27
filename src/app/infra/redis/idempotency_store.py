"""
Idempotency store (Redis-based).

Responsibilities:
- Mark outbound messages as delivered using out_id
- Prevent duplicate delivery on retries
"""

from __future__ import annotations

from src.app.config.settings import settings
from src.app.infra.redis.client import RedisClient
from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


class IdempotencyStore:
    def __init__(self, redis_client: RedisClient) -> None:
        self.redis_client = redis_client

    @staticmethod
    def _key(out_id: str) -> str:
        return f"sent:{out_id}"

    async def was_sent(self, out_id: str) -> bool:
        client = await self.redis_client.get_client()
        val = await client.get(self._key(out_id))
        return val is not None

    async def mark_sent(self, out_id: str) -> None:
        client = await self.redis_client.get_client()
        await client.set(self._key(out_id), "1", ex=settings.outbound_idempotency_ttl_seconds)


"""
Redis client wrapper.

Responsibilities:
- Create and manage a Redis connection
- Centralize Redis configuration
- Provide a reusable async Redis client
- Log connection lifecycle clearly

NOTE:
- This module does NOT know about streams, agents, or supervisors.
- It only provides a Redis connection.
"""

from __future__ import annotations

import redis.asyncio as redis
from typing import Optional

from src.app.config.settings import settings
from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


class RedisClient:
    """
    Thin wrapper around redis.asyncio client.
    """

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> redis.Redis:
        """
        Initialize Redis connection if not already connected.
        """
        if self._client:
            return self._client

        logger.info(
            "Connecting to Redis | host=%s | port=%s | db=%s",
            settings.redis_host,
            settings.redis_port,
            settings.redis_db,
        )

        self._client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True,  # important for streams
        )

        try:
            await self._client.ping()
            logger.info("Redis connection established successfully")
        except Exception as exc:
            logger.error("Failed to connect to Redis", exc_info=exc)
            raise

        return self._client

    async def get_client(self) -> redis.Redis:
        """
        Get an active Redis client.
        """
        if not self._client:
            await self.connect()
        return self._client

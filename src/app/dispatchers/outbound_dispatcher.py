"""
Outbound Dispatcher (delivery runtime).

Responsibilities:
- Consume outbound messages from Redis Stream using consumer groups
- Deliver responses to the correct channel adapter (Twilio WhatsApp for now)
- ACK outbound stream entries only after successful delivery
- Prevent duplicate sends using idempotency keys (out_id)

IMPORTANT:
- Worker does execution and publishes to outbound stream.
- Dispatcher does delivery and ACKs outbound stream entries.
"""

from __future__ import annotations

import asyncio
from typing import Dict

from src.app.config.settings import settings
from src.app.infra.redis_client import RedisClient
from src.app.infra.idempotency_store import IdempotencyStore
from src.app.logging.logger import setup_logger
from src.app.dispatchers.channels.twilio_whatsapp_sender import TwilioWhatsAppSender

logger = setup_logger(__name__)


class OutboundDispatcher:
    def __init__(
        self,
        redis_client: RedisClient,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        max_concurrency: int = 10,
    ) -> None:
        self.redis_client = redis_client
        self.stream_name = stream_name
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.semaphore = asyncio.Semaphore(max_concurrency)

        self.idempotency = IdempotencyStore(redis_client)
        self.twilio_sender = TwilioWhatsAppSender()

    async def start(self) -> None:
        client = await self.redis_client.get_client()
        await self._ensure_consumer_group(client)

        logger.info(
            "Outbound dispatcher started | stream=%s | group=%s | consumer=%s | max_concurrency=%s",
            self.stream_name,
            self.group_name,
            self.consumer_name,
            self.semaphore._value,  # ok for debug
        )

        while True:
            try:
                await self._consume_once(client)
            except Exception as exc:
                logger.error("Dispatcher loop error", exc_info=exc)
                await asyncio.sleep(1)

    async def _ensure_consumer_group(self, client) -> None:
        try:
            await client.xgroup_create(
                name=self.stream_name,
                groupname=self.group_name,
                id="0-0",
                mkstream=True,
            )
            logger.info("Outbound consumer group created | stream=%s | group=%s", self.stream_name, self.group_name)
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.debug("Outbound consumer group already exists | stream=%s | group=%s", self.stream_name, self.group_name)
            else:
                raise

    async def _consume_once(self, client) -> None:
        response = await client.xreadgroup(
            groupname=self.group_name,
            consumername=self.consumer_name,
            streams={self.stream_name: ">"},
            count=10,
            block=5000,
        )
        if not response:
            return

        for _, messages in response:
            for stream_id, payload in messages:
                asyncio.create_task(self._process_with_limit(client, stream_id, payload))

    async def _process_with_limit(self, client, stream_id: str, payload: Dict[str, str]) -> None:
        async with self.semaphore:
            await self._process_one(client, stream_id, payload)

    async def _process_one(self, client, stream_id: str, payload: Dict[str, str]) -> None:
        out_id = (payload.get("out_id") or "").strip()
        source = (payload.get("source") or "unknown").strip()
        user_id = (payload.get("user_id") or "").strip()
        reply_text = (payload.get("reply_text") or "").strip()

        if not out_id or not user_id or not reply_text:
            logger.warning("Invalid outbound payload | stream_id=%s | payload=%s", stream_id, payload)
            # ACK invalid to avoid poisoning outbound stream
            await client.xack(self.stream_name, self.group_name, stream_id)
            return

        # Idempotency check
        if await self.idempotency.was_sent(out_id):
            logger.info("Outbound already delivered (idempotent skip) | out_id=%s | stream_id=%s", out_id, stream_id)
            await client.xack(self.stream_name, self.group_name, stream_id)
            return

        logger.info("Delivering outbound | out_id=%s | source=%s | user_id=%s", out_id, source, user_id)

        try:
            if source == "whatsapp":
                # Twilio expects 'to' in whatsapp format, which inbound already uses.
                sid = self.twilio_sender.send_text(to=user_id, body=reply_text)
                logger.debug("Delivery success | out_id=%s | twilio_sid=%s", out_id, sid)
            else:
                raise ValueError(f"Unsupported outbound source={source!r}")

            await self.idempotency.mark_sent(out_id)

            # ACK only after successful delivery (or idempotent skip)
            await client.xack(self.stream_name, self.group_name, stream_id)
            logger.info("Outbound acknowledged | out_id=%s | stream_id=%s", out_id, stream_id)

        except Exception as exc:
            logger.error("Outbound delivery failed | out_id=%s | stream_id=%s", out_id, stream_id, exc_info=exc)
            # DO NOT ACK on failure -> will retry


async def run_dispatcher() -> None:
    redis_client = RedisClient()
    dispatcher = OutboundDispatcher(
        redis_client=redis_client,
        stream_name=settings.redis_stream_outbound,
        group_name=settings.redis_outbound_consumer_group,
        consumer_name=settings.redis_outbound_consumer_name,
        max_concurrency=getattr(settings, "outbound_max_concurrency", 10),
    )
    await dispatcher.start()


if __name__ == "__main__":
    asyncio.run(run_dispatcher())

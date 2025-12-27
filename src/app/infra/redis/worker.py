"""
Redis Stream worker (execution runtime).

Responsibilities:
- Consume inbound messages from Redis Stream using a consumer group
- Process messages concurrently with a controlled concurrency limit
- (Phase 5) If message contains audio media, run STT first, then pass transcript to supervisor
- Invoke Supervisor for each message
- Publish execution output to outbound Redis Stream (Phase 3)
- ACK inbound messages only after successful processing + outbound publish
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.app.api.twilio.audio_stt import transcribe_twilio_audio
from src.app.api.twilio.media import pick_first_audio_media
from src.app.config.settings import settings
from src.app.infra.redis.client import RedisClient
from src.app.infra.redis.stream_outbound_publisher import RedisStreamOutboundPublisher
from src.app.infra.redis.bootstrap import bootstrap_supervisor
from src.app.logging.logger import setup_logger
from src.app.runtime.output_assembler import extract_reply_text

logger = setup_logger(__name__)


@dataclass(frozen=True)
class InboundContext:
    stream_message_id: str
    source: str
    user_id: str
    text: str
    metadata_json: Optional[str]
    metadata: Dict[str, Any]
    message_id: str  # logical message id published by ingress
    conversation_id: str
    timestamp: Optional[str]


def _parse_iso_ts(ts: Optional[str]) -> Optional[datetime]:
    """Best-effort parse ISO timestamp to aware UTC datetime."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        # If timestamp is naive, assume UTC
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_json_dict(value: Optional[str]) -> Dict[str, Any]:
    """
    Parse a JSON string into a dict; return {} on failure.
    """
    if not value:
        return {}
    try:
        obj = json.loads(value)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _build_inbound_context(stream_message_id: str, payload: Dict[str, str]) -> InboundContext:
    """
    Normalize raw Redis stream payload fields into a strongly typed context object.
    """
    text = (payload.get("text") or "").strip()
    source = payload.get("source", "unknown")
    user_id = payload.get("user_id", "unknown")
    metadata_json = payload.get("metadata")
    metadata = _parse_json_dict(metadata_json)

    message_id = (payload.get("message_id") or "").strip() or stream_message_id
    conversation_id = (payload.get("conversation_id") or "").strip() or message_id
    timestamp = payload.get("timestamp")

    return InboundContext(
        stream_message_id=stream_message_id,
        source=source,
        user_id=user_id,
        text=text,
        metadata_json=metadata_json,
        metadata=metadata,
        message_id=message_id,
        conversation_id=conversation_id,
        timestamp=timestamp,
    )


async def _maybe_transcribe_audio(ctx: InboundContext) -> tuple[str, Optional[str]]:
    """
    Returns:
      (text, immediate_user_reply_if_no_text)

    If inbound text is empty and audio media is present, we run STT and return transcript text.
    If STT fails, returns ("", <user-facing error message>).
    """
    if ctx.text:
        return ctx.text, None

    audio = pick_first_audio_media(ctx.metadata)
    if not audio:
        return "", None

    logger.info(
        "Audio message detected | id=%s | content_type=%s",
        ctx.stream_message_id,
        audio.content_type,
    )
    try:
        transcript, _debug_dir = await transcribe_twilio_audio(
            media_url=audio.url,
            content_type=audio.content_type,
            twilio_account_sid=settings.twilio_account_sid or "",
            twilio_auth_token=settings.twilio_auth_token or "",
            openai_api_key=settings.openai_api_key or "",
            model="whisper-1",
        )
        if transcript:
            logger.info("Audio transcribed | id=%s | chars=%s", ctx.stream_message_id, len(transcript))
            return transcript, None
        logger.warning("Empty transcription result | id=%s", ctx.stream_message_id)
        return "", "Sorry, I couldn't transcribe that voice note. Please try again or send text."
    except Exception:
        logger.exception("STT failed for audio message | id=%s", ctx.stream_message_id)
        return "", "Sorry, I couldn't transcribe that voice note. Please try again or send text."


async def _invoke_supervisor(supervisor: Any, stream_message_id: str, text: str) -> Any:
    """
    Invoke supervisor and return raw result.
    """
    logger.debug("Invoking supervisor | id=%s", stream_message_id)
    t_sup_start = time.perf_counter()
    result = await supervisor.ainvoke({"messages": [{"role": "user", "content": text}]})
    t_sup_end = time.perf_counter()
    logger.info("Supervisor done | id=%s | supervisor_ainvoke_s=%.3f", stream_message_id, (t_sup_end - t_sup_start))
    logger.info("Supervisor result | id=%s | result=%s", stream_message_id, result)
    return result


def _build_outbound_payload(ctx: InboundContext, reply_text: str) -> Dict[str, str]:
    out_payload: Dict[str, str] = {
        "out_id": str(uuid.uuid4()),
        "correlation_id": ctx.message_id,
        "conversation_id": ctx.conversation_id,
        "source": ctx.source,
        "user_id": ctx.user_id,
        "reply_text": reply_text,
        "status": "success",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if ctx.metadata_json:
        try:
            json.loads(ctx.metadata_json)
            out_payload["metadata"] = ctx.metadata_json
        except Exception:
            out_payload["metadata"] = json.dumps({"raw": ctx.metadata_json})

    return out_payload


class RedisStreamWorker:
    """
    Consumes messages from Redis Streams and invokes Supervisor concurrently.
    Produces outbound messages to an outbound Redis Stream.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        supervisor: Any,
        max_concurrency: int = 10,
    ) -> None:
        self.redis_client = redis_client
        self.stream_name = stream_name
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.supervisor = supervisor
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def start(self) -> None:
        """
        Start the worker consume loop (runs forever).
        """
        client = await self.redis_client.get_client()
        await self._ensure_consumer_group(client)

        logger.info(
            "Redis worker started | stream=%s | group=%s | consumer=%s | max_concurrency=%s",
            self.stream_name,
            self.group_name,
            self.consumer_name,
            self.semaphore._value,  # ok for debug
        )

        while True:
            try:
                await self._consume_once(client)
            except Exception as exc:
                logger.error("Worker loop error", exc_info=exc)
                await asyncio.sleep(1)

    async def _ensure_consumer_group(self, client) -> None:
        """
        Ensure consumer group exists.
        """
        try:
            await client.xgroup_create(
                name=self.stream_name,
                groupname=self.group_name,
                id="0-0",
                mkstream=True,
            )
            logger.info(
                "Redis consumer group created | stream=%s | group=%s",
                self.stream_name,
                self.group_name,
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.debug(
                    "Redis consumer group already exists | stream=%s | group=%s",
                    self.stream_name,
                    self.group_name,
                )
            else:
                raise

    async def _consume_once(self, client) -> None:
        """
        Read a small batch and schedule concurrent processing tasks.
        """
        response = await client.xreadgroup(
            groupname=self.group_name,
            consumername=self.consumer_name,
            streams={self.stream_name: ">"},
            count=10,
            block=5000,  # ms
        )

        if not response:
            return

        for _, messages in response:
            for message_id, payload in messages:
                asyncio.create_task(self._process_with_limit(client, message_id, payload))

    async def _process_with_limit(self, client, message_id: str, payload: Dict[str, str]) -> None:
        """
        Apply concurrency limit and then process the message.
        """
        async with self.semaphore:
            await self._process_message(client, message_id, payload)

    async def _process_message(self, client, message_id: str, payload: Dict[str, str]) -> None:
        """
        Invoke Supervisor for a single message, publish outbound output, ACK on success.

        ACK rule (Phase 3):
        - ACK inbound only after outbound publish succeeds.
        """
        t_total_start = time.perf_counter()

        ctx = _build_inbound_context(message_id, payload)

        # Measure ingress-to-worker lag if inbound timestamp exists
        ingress_ts = _parse_iso_ts(ctx.timestamp)
        if ingress_ts:
            lag_s = (datetime.now(timezone.utc) - ingress_ts).total_seconds()
            logger.info("Inbound lag | id=%s | lag_s=%.3f", message_id, lag_s)

        # Phase 5: Media-aware ingress. If text is empty but there is audio media, run STT first.
        text, immediate_reply = await _maybe_transcribe_audio(ctx)
        result: Any = immediate_reply

        if not text and result is None:
            logger.warning("Empty text message | id=%s | payload=%s", ctx.stream_message_id, payload)
            await client.xack(self.stream_name, self.group_name, message_id)
            return

        logger.info(
            "Processing message | id=%s | source=%s | user_id=%s | text=%s",
            ctx.stream_message_id,
            ctx.source,
            ctx.user_id,
            text,
        )

        try:
            if result is None:
                result = await _invoke_supervisor(self.supervisor, ctx.stream_message_id, text)

            # Output extraction
            t_extract_start = time.perf_counter()
            reply_text = extract_reply_text(result) or "Done."
            t_extract_end = time.perf_counter()
            logger.info("Reply ready | id=%s | chars=%s | reply=%s", ctx.stream_message_id, len(reply_text), reply_text)

            out_payload = _build_outbound_payload(ctx, reply_text)

            # Outbound publish
            outbound_publisher = RedisStreamOutboundPublisher(
                redis_client=self.redis_client,
                stream_name=settings.redis_stream_outbound,
            )

            t_pub_start = time.perf_counter()
            outbound_stream_id = await outbound_publisher.publish_output(out_payload)
            t_pub_end = time.perf_counter()

            logger.info(
                "Outbound published | outbound_stream_id=%s | correlation_id=%s | user_id=%s | publish_outbound_s=%.3f",
                outbound_stream_id,
                out_payload.get("correlation_id", "unknown"),
                out_payload.get("user_id", "unknown"),
                (t_pub_end - t_pub_start),
            )

            # ACK only after outbound publish
            t_ack_start = time.perf_counter()
            await client.xack(self.stream_name, self.group_name, message_id)
            t_ack_end = time.perf_counter()

            t_total_end = time.perf_counter()

            logger.info(
                "Message acknowledged | id=%s | timings: extract_reply=%.3f s | publish=%.3f s | ack=%.3f s | total=%.3f s",
                ctx.stream_message_id,
                (t_extract_end - t_extract_start),
                (t_pub_end - t_pub_start),
                (t_ack_end - t_ack_start),
                (t_total_end - t_total_start),
            )

        except Exception as exc:
            logger.error("Failed to process message | id=%s", ctx.stream_message_id, exc_info=exc)
            # DO NOT ACK on failure. Message stays pending.


async def run_worker() -> None:
    """
    Script entrypoint for running this worker process.
    Creates Supervisor once, then consumes messages forever.
    """
    supervisor = await bootstrap_supervisor()

    redis_client = RedisClient()
    worker = RedisStreamWorker(
        redis_client=redis_client,
        stream_name=settings.redis_stream_inbound,
        group_name=settings.redis_consumer_group,
        consumer_name=settings.redis_consumer_name,
        supervisor=supervisor,
        max_concurrency=getattr(settings, "worker_max_concurrency", 10),
    )

    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_worker())


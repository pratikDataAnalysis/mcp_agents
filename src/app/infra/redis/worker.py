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
import shutil
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.app.config.settings import settings
from src.app.audio.media import build_media_root_path, build_public_media_url, ensure_dir, guess_mime_type_from_audio_format
from src.app.infra.redis.client import RedisClient
from src.app.infra.redis.memory_store import RedisMemoryStore
from src.app.infra.redis.memory_store import MemoryContext
from src.app.infra.redis.stream_outbound_publisher import RedisStreamOutboundPublisher
from src.app.infra.redis.bootstrap import bootstrap_supervisor
from src.app.logging.logger import setup_logger
from src.app.mcp.tools.language_tools import localAudio_text_to_speech
from src.app.runtime.pre_supervisor import prepare_for_supervisor
from src.app.runtime.output_assembler import extract_reply_text
from src.app.infra.tool_execution_tracker import any_grounded_success, reset_tool_events

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


def _truncate(s: str, limit: int = 500) -> str:
    s2 = (s or "").strip()
    if len(s2) <= limit:
        return s2
    return s2[: max(0, limit - 3)] + "..."


def _compact_memory_context(ctx: MemoryContext) -> Dict[str, Any]:
    """
    Build a compact, token-safe memory blob to inject into the supervisor envelope.
    """
    # Keep memory small and stable. We mainly want recent events + a couple of profile fields.
    user_profile = ctx.user_profile if isinstance(ctx.user_profile, dict) else None
    if isinstance(user_profile, dict):
        user_profile = {
            "schema": user_profile.get("schema"),
            "user_id": user_profile.get("user_id"),
            "last_seen_at": user_profile.get("last_seen_at"),
            "last_detected_language": user_profile.get("last_detected_language"),
            "reply_in_audio_when_inbound_audio": user_profile.get("reply_in_audio_when_inbound_audio"),
        }

    max_events = 5
    events_out = []
    for e in (ctx.recent_events or [])[:max_events]:
        if not isinstance(e, dict):
            continue
        events_out.append(
            {
                "ts": e.get("ts"),
                "conversation_id": e.get("conversation_id"),
                "original_text": _truncate(str(e.get("original_text") or "")),
                "english_text": _truncate(str(e.get("english_text") or "")),
                "reply_text": _truncate(str(e.get("reply_text") or "")),
                "actions": e.get("actions") if isinstance(e.get("actions"), list) else [],
            }
        )

    return {
        "user_profile": user_profile,
        "recent_events": events_out,
    }


def _inject_memory_into_envelope(supervisor_input: str, memory_context: Dict[str, Any]) -> str:
    """
    Inject memory_context into the INPUT_ENVELOPE_JSON payload so the supervisor can route without a memory tool call.
    """
    prefix = "INPUT_ENVELOPE_JSON:\n"
    if not supervisor_input.startswith(prefix):
        return supervisor_input
    raw = supervisor_input[len(prefix) :].strip()
    try:
        envelope = json.loads(raw)
    except Exception:
        return supervisor_input
    if not isinstance(envelope, dict):
        return supervisor_input
    envelope["memory_context"] = memory_context
    return prefix + json.dumps(envelope, ensure_ascii=False) + "\n"


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


async def _invoke_supervisor(supervisor: Any, ctx: InboundContext, text: str) -> Any:
    """
    Invoke supervisor and return raw result.
    """
    logger.debug("Invoking supervisor | id=%s", ctx.stream_message_id)
    t_sup_start = time.perf_counter()
    # LangSmith metadata (when enabled via env):
    # - thread_id groups traces per conversation
    # - metadata provides quick filters/search
    config = {
        "configurable": {
            "thread_id": ctx.conversation_id,
            "conversation_id": ctx.conversation_id,
            "user_id": ctx.user_id,
        },
        "tags": [ctx.source],
        "metadata": {
            "stream_message_id": ctx.stream_message_id,
            "message_id": ctx.message_id,
            "conversation_id": ctx.conversation_id,
            "source": ctx.source,
            "user_id": ctx.user_id,
        },
    }
    result = await supervisor.ainvoke({"messages": [{"role": "user", "content": text}]}, config=config)
    t_sup_end = time.perf_counter()
    logger.info("Supervisor done | id=%s | supervisor_ainvoke_s=%.3f", ctx.stream_message_id, (t_sup_end - t_sup_start))
    logger.info("Supervisor result | id=%s | result=%s", ctx.stream_message_id, result)
    return result


def _extract_structured_fields(result: Any) -> tuple[Optional[str], list[str], Optional[str]]:
    """
    Extract (status, actions, task_instructions) from supervisor result if present.
    """
    status: Optional[str] = None
    actions: list[str] = []
    task_instructions: Optional[str] = None

    if isinstance(result, dict):
        ti = result.get("task_instructions")
        if isinstance(ti, str) and ti.strip():
            task_instructions = ti.strip()

        sr = result.get("structured_response")

        # Pydantic-like object
        st = getattr(sr, "status", None)
        if isinstance(st, str) and st.strip():
            status = st.strip()
        acts = getattr(sr, "actions", None)
        if isinstance(acts, list):
            actions = [str(x) for x in acts if str(x).strip()]

        # Dict-like
        if isinstance(sr, dict):
            st2 = sr.get("status")
            if isinstance(st2, str) and st2.strip():
                status = st2.strip()
            acts2 = sr.get("actions")
            if isinstance(acts2, list):
                actions = [str(x) for x in acts2 if str(x).strip()]

    return status, actions, task_instructions


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


async def _maybe_build_audio_reply(*, reply_text: str) -> Optional[Dict[str, str]]:
    """
    Generate a TTS audio reply and return outbound fields:
      { "reply_audio_url": "...", "reply_audio_mime_type": "..." }
    """
    if not settings.reply_with_audio_when_inbound_has_audio:
        return None

    # Synthesize speech to a temp file (tool returns local file path)
    tts = await localAudio_text_to_speech.ainvoke(
        {
            "text": reply_text,
            "voice": settings.tts_voice,
            "model": settings.tts_model_name,
            "format": settings.tts_format,
        }
    )
    if not isinstance(tts, dict):
        return None

    src_path = (tts.get("file_path") or "").strip()
    fmt = (tts.get("format") or settings.tts_format or "mp3").strip()
    if not src_path:
        return None

    # Copy into a stable, ingress-served directory (shared volume in local dev)
    filename = f"{uuid.uuid4().hex}.{fmt}"
    rel_path = f"tts/{filename}"
    dst_path = build_media_root_path(rel_path=rel_path)
    ensure_dir(str(__import__("pathlib").Path(dst_path).parent))
    shutil.copy2(src_path, dst_path)

    url = build_public_media_url(rel_path=rel_path)
    if not url:
        # Without a public base URL, Twilio cannot fetch media.
        logger.warning(
            "TTS generated but media_public_base_url is not set; skipping audio reply delivery | dst_path=%s",
            dst_path,
        )
        return None

    return {
        "reply_audio_url": url,
        "reply_audio_mime_type": guess_mime_type_from_audio_format(fmt),
    }


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

        pre = await prepare_for_supervisor(ctx=ctx, metadata=ctx.metadata)
        result: Any = pre.immediate_reply

        if pre.immediate_reply is not None:
            logger.info(
                "Immediate reply (pre-supervisor) | id=%s | reply=%s",
                ctx.stream_message_id,
                pre.immediate_reply,
            )
        else:
            logger.info(
                "Processing message | id=%s | source=%s | user_id=%s | detected_lang=%s | is_english=%s | inbound_has_audio=%s",
                ctx.stream_message_id,
                ctx.source,
                ctx.user_id,
                pre.detected_language,
                pre.is_english,
                pre.inbound_has_audio,
            )

        try:
            if result is None:
                # Reset tool execution tracker for this request context.
                # This makes grounding detection independent of supervisor output_mode.
                reset_tool_events()
                # Prefetch memory in worker to avoid an extra supervisor model call (memory_get_context).
                try:
                    mem = RedisMemoryStore(self.redis_client)
                    mem_ctx = await mem.get_context(user_id=ctx.user_id, conversation_id=ctx.conversation_id)
                    supervisor_input = _inject_memory_into_envelope(
                        pre.supervisor_input,
                        _compact_memory_context(mem_ctx),
                    )
                except Exception as exc:
                    logger.warning("Memory prefetch failed; continuing without memory_context | id=%s", ctx.stream_message_id, exc_info=exc)
                    supervisor_input = pre.supervisor_input

                result = await _invoke_supervisor(self.supervisor, ctx, supervisor_input)

            # Output extraction
            t_extract_start = time.perf_counter()
            reply_text = extract_reply_text(result) or "Done."
            t_extract_end = time.perf_counter()
            logger.info("Reply ready | id=%s | chars=%s | reply=%s", ctx.stream_message_id, len(reply_text), reply_text)

            out_payload = _build_outbound_payload(ctx, reply_text)

            # Optional: if inbound contained audio, attach an audio reply URL (TTS)
            if pre.inbound_has_audio:
                try:
                    audio_fields = await _maybe_build_audio_reply(reply_text=reply_text)
                    if audio_fields:
                        out_payload.update(audio_fields)
                except Exception as exc:
                    logger.warning("Audio reply TTS failed; continuing with text-only | id=%s", ctx.stream_message_id, exc_info=exc)

            # Deterministic memory write: only on successful supervisor outcome.
            try:
                status, actions, task_instructions = _extract_structured_fields(result)
                status_norm = (status or "").strip().lower()
                grounded = any_grounded_success(count_local_audio=False)
                if status_norm == "success" and grounded:
                    mem = RedisMemoryStore(self.redis_client)
                    await mem.safe_write_success(
                        user_id=ctx.user_id,
                        conversation_id=ctx.conversation_id,
                        original_text=getattr(pre, "original_text", None),
                        english_text=getattr(pre, "english_text", None),
                        detected_language=pre.detected_language,
                        inbound_has_audio=pre.inbound_has_audio,
                        reply_text=reply_text,
                        actions=actions,
                        task_instructions=task_instructions,
                        reply_audio_url=out_payload.get("reply_audio_url"),
                        write_user_event=True,
                    )
                else:
                    logger.info(
                        "Memory write skipped | id=%s | status=%s | grounded=%s",
                        ctx.stream_message_id,
                        status_norm or "unknown",
                        grounded,
                    )
            except Exception as exc:
                logger.warning("Memory write step failed; continuing | id=%s", ctx.stream_message_id, exc_info=exc)

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


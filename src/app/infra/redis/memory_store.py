"""
Redis-backed memory store (JSON).

Design goals:
- Deterministic, worker-driven writes (do not rely on the LLM to "remember")
- Cheap reads (small fixed number of keys)
- Schema/versioned documents for safe evolution
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

import uuid

from src.app.config.settings import settings
from src.app.infra.redis.client import RedisClient
from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _k(*parts: str) -> str:
    prefix = (settings.memory_key_prefix or "mem").strip(":") or "mem"
    safe_parts = [p.strip(":") for p in parts if p]
    return ":".join([prefix, *safe_parts])


@dataclass(frozen=True)
class MemoryContext:
    user_profile: Optional[Dict[str, Any]]
    conversation_state: Optional[Dict[str, Any]]
    recent_events: List[Dict[str, Any]]


class RedisMemoryStore:
    def __init__(self, redis_client: RedisClient) -> None:
        self.redis_client = redis_client

    def _user_profile_key(self, user_id: str) -> str:
        return _k("user", user_id, "profile")

    def _conversation_state_key(self, conversation_id: str) -> str:
        return _k("conv", conversation_id, "state")

    def _user_events_key(self, user_id: str) -> str:
        return _k("user", user_id, "events")

    async def get_context(self, *, user_id: str, conversation_id: str) -> MemoryContext:
        """
        Fetch user + conversation memory in one pipelined read.
        """
        client = await self.redis_client.get_client()
        up_key = self._user_profile_key(user_id)
        cs_key = self._conversation_state_key(conversation_id)
        ev_key = self._user_events_key(user_id)
        max_items = int(getattr(settings, "memory_user_events_max_items", 15) or 15)
        max_items = max(1, min(max_items, 200))

        logger.debug(
            "Memory read | prefix=%s | user_profile_key=%s | conv_state_key=%s | events_key=%s | events_max=%s",
            (settings.memory_key_prefix or "mem"),
            up_key,
            cs_key,
            ev_key,
            max_items,
        )

        pipe = client.pipeline()
        pipe.get(up_key)
        pipe.get(cs_key)
        pipe.lrange(ev_key, 0, max_items - 1)
        raw_up, raw_cs, raw_events = await pipe.execute()

        def parse(raw: Any) -> Optional[Dict[str, Any]]:
            if not raw or not isinstance(raw, str):
                return None
            try:
                obj = json.loads(raw)
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None

        user_profile = parse(raw_up)
        conv_state = parse(raw_cs)

        events: List[Dict[str, Any]] = []
        if isinstance(raw_events, list):
            for item in raw_events:
                if not isinstance(item, str) or not item.strip():
                    continue
                try:
                    obj = json.loads(item)
                    if isinstance(obj, dict):
                        events.append(obj)
                except Exception:
                    continue

        logger.debug(
            "Memory read result | user_profile=%s | conversation_state=%s | events=%s",
            "hit" if user_profile else "miss",
            "hit" if conv_state else "miss",
            len(events),
        )
        return MemoryContext(user_profile=user_profile, conversation_state=conv_state, recent_events=events)

    async def append_user_event(self, *, user_id: str, event: Dict[str, Any]) -> None:
        """
        Append an event to the user's event history (bounded list with TTL).
        Newest first.
        """
        client = await self.redis_client.get_client()
        key = self._user_events_key(user_id)
        max_items = int(getattr(settings, "memory_user_events_max_items", 15) or 15)
        max_items = max(1, min(max_items, 200))
        ttl = int(getattr(settings, "memory_user_events_ttl_seconds", 0) or 0)

        payload = json.dumps(event, ensure_ascii=False)

        pipe = client.pipeline()
        pipe.lpush(key, payload)
        pipe.ltrim(key, 0, max_items - 1)
        if ttl > 0:
            pipe.expire(key, ttl)
        await pipe.execute()

        logger.debug("Memory write | kind=user_event | key=%s | ttl_s=%s | max_items=%s", key, ttl, max_items)

    async def upsert_user_profile(
        self,
        *,
        user_id: str,
        patch: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Upsert user profile JSON.
        """
        client = await self.redis_client.get_client()
        key = self._user_profile_key(user_id)

        existing_raw = await client.get(key)
        existing: Dict[str, Any] = {}
        if isinstance(existing_raw, str) and existing_raw.strip():
            try:
                obj = json.loads(existing_raw)
                if isinstance(obj, dict):
                    existing = obj
            except Exception:
                existing = {}

        base = {
            "schema": existing.get("schema") or "user_profile_v1",
            "user_id": user_id,
            "created_at": existing.get("created_at") or _now_iso(),
        }
        merged = {**existing, **base, **patch, "updated_at": _now_iso()}

        ttl = int(getattr(settings, "memory_user_profile_ttl_seconds", 0) or 0)
        payload = json.dumps(merged, ensure_ascii=False)
        logger.debug("Memory write | kind=user_profile | key=%s | ttl_s=%s", key, ttl)
        if ttl > 0:
            await client.setex(key, ttl, payload)
        else:
            await client.set(key, payload)
        return merged

    async def upsert_conversation_state(
        self,
        *,
        conversation_id: str,
        user_id: str,
        patch: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Upsert conversation state JSON with TTL.
        """
        client = await self.redis_client.get_client()
        key = self._conversation_state_key(conversation_id)

        existing_raw = await client.get(key)
        existing: Dict[str, Any] = {}
        if isinstance(existing_raw, str) and existing_raw.strip():
            try:
                obj = json.loads(existing_raw)
                if isinstance(obj, dict):
                    existing = obj
            except Exception:
                existing = {}

        base = {
            "schema": existing.get("schema") or "conversation_state_v1",
            "conversation_id": conversation_id,
            "user_id": user_id,
            "created_at": existing.get("created_at") or _now_iso(),
        }
        merged = {**existing, **base, **patch, "updated_at": _now_iso()}

        ttl = int(getattr(settings, "memory_conversation_ttl_seconds", 0) or 0)
        if ttl <= 0:
            ttl = 12 * 60 * 60
        logger.debug("Memory write | kind=conversation_state | key=%s | ttl_s=%s", key, ttl)
        await client.setex(key, ttl, json.dumps(merged, ensure_ascii=False))
        return merged

    async def safe_write_success(
        self,
        *,
        user_id: str,
        conversation_id: str,
        original_text: Optional[str] = None,
        english_text: Optional[str] = None,
        detected_language: Optional[str],
        inbound_has_audio: bool,
        reply_text: str,
        actions: Optional[list[str]] = None,
        task_instructions: Optional[str] = None,
        reply_audio_url: Optional[str] = None,
        write_user_event: bool = True,
    ) -> None:
        """
        Best-effort memory write for successful operations.
        Never raises (memory must not break user replies).
        """
        try:
            logger.info(
                "Memory write (success) | user_id=%s | conversation_id=%s | detected_language=%s | inbound_has_audio=%s | has_audio_url=%s",
                user_id,
                conversation_id,
                detected_language,
                inbound_has_audio,
                bool(reply_audio_url),
            )
            await self.upsert_conversation_state(
                conversation_id=conversation_id,
                user_id=user_id,
                patch={
                    "last_status": "success",
                    "last_original_text": original_text,
                    "last_english_text": english_text,
                    "last_reply_text": reply_text,
                    "last_actions": actions or [],
                    "last_task_instructions": task_instructions,
                    "detected_language_last": detected_language,
                    "inbound_has_audio_last": inbound_has_audio,
                    "reply_audio_url_last": reply_audio_url,
                },
            )

            # Keep user profile minimal + safe: only “last seen” style facts.
            await self.upsert_user_profile(
                user_id=user_id,
                patch={
                    "last_seen_at": _now_iso(),
                    "last_detected_language": detected_language,
                    **(
                        {"reply_in_audio_when_inbound_audio": True}
                        if inbound_has_audio
                        else {}
                    ),
                },
            )

            if write_user_event:
                # Append to user-level history so we can answer "what were my previous messages about?"
                event = {
                    "schema": "memory_event_v1",
                    "event_id": str(uuid.uuid4()),
                    "ts": _now_iso(),
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "original_text": (original_text or "").strip(),
                    "english_text": (english_text or "").strip(),
                    "reply_text": reply_text,
                    "detected_language": detected_language,
                    "inbound_has_audio": inbound_has_audio,
                    "actions": actions or [],
                    "task_instructions": task_instructions,
                    "reply_audio_url": reply_audio_url,
                }
                await self.append_user_event(user_id=user_id, event=event)
            else:
                logger.info(
                    "Memory write skipped | kind=user_event | reason=not_grounded | user_id=%s | conversation_id=%s",
                    user_id,
                    conversation_id,
                )
        except Exception as exc:
            logger.warning(
                "Memory write skipped due to error | user_id=%s | conversation_id=%s",
                user_id,
                conversation_id,
                exc_info=exc,
            )



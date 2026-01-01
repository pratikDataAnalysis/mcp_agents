"""
Supervisor-level memory tools (Redis-backed).

We expose READ operations to the supervisor/agents so they can fetch user/conversation
context when needed.

Writes are intentionally handled deterministically in the worker after successful runs
to avoid noisy/incorrect LLM-driven memory updates.
"""

from __future__ import annotations

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

from src.app.infra.redis import RedisClient, RedisMemoryStore
from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)

def _truncate(s: str, limit: int = 600) -> str:
    s2 = (s or "").strip()
    if len(s2) <= limit:
        return s2
    return s2[: max(0, limit - 3)] + "..."


@tool(name_or_callable="memory_get_context")
async def memory_get_context(config: RunnableConfig) -> dict:
    """
    Fetch Redis-backed memory context for the current user + conversation.

    Returns:
      {
        "user_profile": {...} | null,
        "conversation_state": {...} | null
      }
    """
    cfg = config.get("configurable") or {}
    user_id = (cfg.get("user_id") or "").strip()
    conversation_id = (cfg.get("conversation_id") or cfg.get("thread_id") or "").strip()

    if not user_id or not conversation_id:
        logger.debug("memory_get_context: missing identifiers | user_id=%s | conversation_id=%s", bool(user_id), bool(conversation_id))
        return {"user_profile": None, "conversation_state": None}

    redis_client = RedisClient()
    store = RedisMemoryStore(redis_client)
    ctx = await store.get_context(user_id=user_id, conversation_id=conversation_id)
    logger.debug(
        "memory_get_context: fetched | user_id=%s | conversation_id=%s | user_profile=%s | conversation_state=%s",
        user_id,
        conversation_id,
        "hit" if ctx.user_profile else "miss",
        "hit" if ctx.conversation_state else "miss",
    )

    # Keep payload small to avoid token blow-ups:
    events = []
    for e in (ctx.recent_events or []):
        if not isinstance(e, dict):
            continue
        events.append(
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
        "user_profile": ctx.user_profile,
        "conversation_state": ctx.conversation_state,
        "recent_events": events,
    }



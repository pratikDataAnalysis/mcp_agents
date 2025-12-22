"""
Output assembly helpers.

Responsibilities:
- Convert Supervisor results (various shapes) into a stable reply_text string
- Never leak internal tool-transfer / routing messages to end users
- Prefer supervisor final message (Option B)
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


def _is_handoff_or_internal(msg: BaseMessage) -> bool:
    """
    Generic filter for internal plumbing messages.

    We intentionally DO NOT hardcode per-agent tool lists.
    We only use framework-level signals:
    - response_metadata['__is_handoff_back'] set by supervisor handoff logic
    - tool_calls containing transfer_back_to_supervisor
    - ToolMessage types
    """
    if isinstance(msg, ToolMessage):
        return True

    # Some handoff-back AI messages carry this metadata
    md = getattr(msg, "response_metadata", None) or {}
    if isinstance(md, dict) and md.get("__is_handoff_back") is True:
        return True

    # Some internal "transfer back" messages appear as AIMessage tool calls
    if isinstance(msg, AIMessage):
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            try:
                name = (tc.get("name") or "").strip()
            except Exception:
                name = ""
            if name == "transfer_back_to_supervisor":
                return True

    return False


def _content(msg: BaseMessage) -> str:
    return (getattr(msg, "content", "") or "").strip()


def _pick_last_supervisor_answer(messages: list[BaseMessage]) -> Optional[str]:
    """
    Option B: prefer the last non-empty supervisor AIMessage content.
    """
    for m in reversed(messages):
        if _is_handoff_or_internal(m):
            continue
        if isinstance(m, AIMessage) and getattr(m, "name", None) == "supervisor":
            c = _content(m)
            if c:
                return c
    return None


def _pick_last_non_internal_answer(messages: list[BaseMessage]) -> Optional[str]:
    """
    Fallback: last non-empty AIMessage content, excluding internal/handoff messages.
    """
    for m in reversed(messages):
        if _is_handoff_or_internal(m):
            continue
        if isinstance(m, AIMessage):
            c = _content(m)
            if c:
                return c
    return None


def extract_reply_text(result: Any) -> str:
    """
    Best-effort extraction of a user-facing reply text from LangChain/LangGraph results.

    Priority:
    1) Supervisor final answer (Option B)
    2) Fallback to last non-internal AI message
    3) Otherwise empty string
    """
    if result is None:
        return ""

    # Plain string
    if isinstance(result, str):
        return result.strip()

    # Direct message object
    if isinstance(result, BaseMessage):
        if _is_handoff_or_internal(result):
            return ""
        return _content(result)

    # Dict-like state (LangGraph often returns dict state)
    if isinstance(result, dict):
        out = result.get("output")
        if isinstance(out, str) and out.strip():
            return out.strip()

        msgs = result.get("messages")
        if isinstance(msgs, list) and msgs:
            if isinstance(msgs[0], BaseMessage):
                supervisor_ans = _pick_last_supervisor_answer(msgs)  # type: ignore[arg-type]
                if supervisor_ans:
                    logger.debug("Reply selected | source=supervisor")
                    return supervisor_ans

                fallback = _pick_last_non_internal_answer(msgs)  # type: ignore[arg-type]
                if fallback:
                    logger.debug("Reply selected | source=fallback_last_ai")
                    return fallback

                logger.debug("Reply empty | reason=no_user_facing_message_found")
                return ""

            # dict-shaped messages fallback
            # Prefer supervisor -> else last assistant, skip tool
            for m in reversed(msgs):
                if not isinstance(m, dict):
                    continue
                role = (m.get("role") or "").lower()
                name = m.get("name")
                content = (m.get("content") or "").strip()
                if not content or role == "tool":
                    continue
                if name == "supervisor":
                    logger.debug("Reply selected | source=supervisor_dict")
                    return content

            for m in reversed(msgs):
                if isinstance(m, dict):
                    role = (m.get("role") or "").lower()
                    content = (m.get("content") or "").strip()
                    if content and role != "tool":
                        logger.debug("Reply selected | source=fallback_dict")
                        return content

    return ""

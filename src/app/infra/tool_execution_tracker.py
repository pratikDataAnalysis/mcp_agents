"""
Tool execution tracking for a single request using contextvars.

Why:
- We want to persist memory ONLY when a request was "grounded" in real tool calls.
- We cannot rely on supervisor output_mode="full_history" always returning ToolMessages.
- contextvars propagate across awaits, so this works across the whole supervisor/agent run.
"""

from __future__ import annotations

import contextvars
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ToolExecutionEvent:
    name: str
    ok: bool


@dataclass
class ToolExecutionCollector:
    """
    Mutable collector stored in a ContextVar.

    Important: we mutate this collector in-place so tool executions recorded from child
    asyncio tasks are visible to the parent task (when the collector object is copied
    into those tasks at creation time).
    """

    events: List[ToolExecutionEvent] = field(default_factory=list)


# Default is None so we don't accidentally share a global mutable default collector.
# The worker MUST call reset_tool_events() before invoking supervisor.
_collector_var: contextvars.ContextVar[Optional[ToolExecutionCollector]] = contextvars.ContextVar(
    "tool_execution_collector",
    default=None,
)


def _get_collector() -> ToolExecutionCollector:
    col = _collector_var.get()
    if col is None:
        col = ToolExecutionCollector()
        _collector_var.set(col)
    return col


def reset_tool_events() -> None:
    """
    Reset tool events for the current request context.
    Call this right before invoking supervisor for a message.
    """
    _collector_var.set(ToolExecutionCollector())


def record_tool_event(*, name: str, ok: bool) -> None:
    # Mutate in-place so updates from child tasks are visible to the parent task.
    _get_collector().events.append(ToolExecutionEvent(name=name, ok=ok))


def snapshot_tool_events() -> List[ToolExecutionEvent]:
    return list(_get_collector().events)


def _result_is_error_like(result: Any) -> bool:
    """
    Best-effort check for tool failures.
    - Validation wrapper returns JSON strings with error_type=validation_error
    - Some tools may return {"object":"error"} or {"error": ...}
    """
    if result is None:
        return True

    # Common: wrapper returns a JSON string error payload
    if isinstance(result, str):
        s = result.strip()
        if not s:
            return True
        try:
            obj = json.loads(s)
        except Exception:
            # A plain string could still be a "success" response; treat as ok.
            return False
        if isinstance(obj, dict):
            if obj.get("error_type"):
                return True
            if obj.get("object") == "error":
                return True
            if obj.get("error"):
                return True
        return False

    if isinstance(result, dict):
        if result.get("error_type"):
            return True
        if result.get("object") == "error":
            return True
        if result.get("error"):
            return True
        status = result.get("status") or result.get("status_code")
        try:
            if isinstance(status, int) and status >= 400:
                return True
        except Exception:
            pass

    return False


_INTERNAL_TOOL_PREFIXES = (
    "transfer_to_",
)

_INTERNAL_TOOL_NAMES = {
    "transfer_back_to_supervisor",
    "memory_get_context",
    "get_current_datetime",
}


def is_internal_tool_name(name: Optional[str]) -> bool:
    if not isinstance(name, str) or not name.strip():
        return True
    n = name.strip()
    if n in _INTERNAL_TOOL_NAMES:
        return True
    if any(n.startswith(p) for p in _INTERNAL_TOOL_PREFIXES):
        return True
    return False


def record_tool_result(*, name: str, result: Any) -> None:
    """
    Convenience: record a tool execution with ok/fail inferred from result.
    """
    ok = not _result_is_error_like(result)
    record_tool_event(name=name, ok=ok)


def any_grounded_success(*, count_local_audio: bool = False) -> bool:
    """
    True if at least one non-internal tool executed successfully.

    By default we do NOT count localAudio_* as grounding (they are "internal plumbing").
    You can opt-in with count_local_audio=True.
    """
    for ev in snapshot_tool_events():
        if not ev.ok:
            continue
        if is_internal_tool_name(ev.name):
            continue
        if not count_local_audio and ev.name.startswith("localAudio_"):
            continue
        return True
    return False



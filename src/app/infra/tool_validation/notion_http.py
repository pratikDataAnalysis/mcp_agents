from __future__ import annotations

import json
import time
from typing import Any, Optional

from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)

# Keyed by (tool_name, message) -> (repeat_count, last_seen_ts)
_NOTION_VALIDATION_REPEAT: dict[tuple[str, str], tuple[int, float]] = {}
_REPEAT_WINDOW_S = 60.0


def maybe_extract_json_text(result: Any) -> Optional[str]:
    """
    Best-effort extraction of JSON-ish text from MCP tool returns.

    Observed shapes include:
    - list[{"type":"text","text":"{...json...}"}]
    - plain string "{...json...}"
    """
    if isinstance(result, str):
        return result
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            txt = first.get("text")
            if isinstance(txt, str):
                return txt
    return None


def normalize_notion_http_validation_error(tool_name: str, result: Any) -> Optional[str]:
    """
    Detect Notion HTTP 400 validation_error payloads and normalize them into a stable
    error_type=validation_error contract so agents can reliably repair/stop.
    """
    txt = maybe_extract_json_text(result)
    if not txt:
        return None
    try:
        data = json.loads(txt)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("status") != 400 or data.get("code") != "validation_error":
        return None

    msg = str(data.get("message") or "")
    key = (tool_name, msg)

    now = time.time()
    prev = _NOTION_VALIDATION_REPEAT.get(key)
    if prev and (now - prev[1]) <= _REPEAT_WINDOW_S:
        count = prev[0] + 1
    else:
        count = 1
    _NOTION_VALIDATION_REPEAT[key] = (count, now)

    payload = {
        "error_type": "validation_error",
        "source": "notion_http_validation",
        "tool": tool_name,
        "message": msg,
        "request_id": data.get("request_id"),
        "repeat_count": count,
        "retry_policy": "retry_once_then_stop",
        "guidance": (
            "Fix request payload to match Notion page/block shapes. "
            "If repeat_count>=2, stop retrying and ask for clarification."
        ),
        "raw": data,
    }
    return json.dumps(payload, ensure_ascii=False)


def log_normalized_notion_error(tool_name: str, normalized_json: str) -> None:
    try:
        repeat = json.loads(normalized_json).get("repeat_count")
    except Exception:
        repeat = None
    logger.warning(
        "Normalized Notion HTTP validation_error | tool=%s | repeat_count=%s",
        tool_name,
        repeat,
    )


"""
Tool output trimming to reduce token usage.

Primary goal:
- Prevent large tool outputs (especially Notion MCP JSON) from being fed back into the LLM
  as ToolMessages, which can spike prompt tokens (often 10k–20k per run).

We keep outputs "LLM-useful" by returning compact summaries with stable schemas.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.app.config.settings import settings


def _safe_json_loads(s: str) -> Optional[Any]:
    try:
        return json.loads(s)
    except Exception:
        return None


def _truncate(s: str, limit: int) -> str:
    s2 = (s or "").strip()
    if limit <= 0 or len(s2) <= limit:
        return s2
    return s2[: max(0, limit - 3)] + "..."


def _extract_title_from_notion_page(page: Dict[str, Any]) -> str:
    props = page.get("properties") if isinstance(page.get("properties"), dict) else {}
    title_prop = props.get("title") if isinstance(props, dict) else None
    if isinstance(title_prop, dict) and title_prop.get("type") == "title":
        parts = title_prop.get("title")
        if isinstance(parts, list) and parts:
            # prefer plain_text fields
            plain = []
            for p in parts:
                if isinstance(p, dict):
                    t = p.get("plain_text") or p.get("text", {}).get("content")  # type: ignore[union-attr]
                    if isinstance(t, str) and t.strip():
                        plain.append(t.strip())
            if plain:
                return " ".join(plain).strip()
    # fallback
    return str(page.get("id") or "").strip()


def _summarize_notion_search(payload: Dict[str, Any], *, query: Optional[str]) -> Dict[str, Any]:
    max_items = int(getattr(settings, "tool_trim_notion_max_items", 5) or 5)
    max_items = max(1, min(max_items, 20))

    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    out_results: List[Dict[str, Any]] = []
    for item in results[:max_items]:
        if not isinstance(item, dict):
            continue
        out_results.append(
            {
                "id": item.get("id"),
                "title": _extract_title_from_notion_page(item),
                "url": item.get("url"),
                "created_time": item.get("created_time"),
                "last_edited_time": item.get("last_edited_time"),
                "parent": item.get("parent"),
                "object": item.get("object"),
            }
        )

    return {
        "schema": "notion_search_summary_v1",
        "query": query,
        "count": len(out_results),
        "results": out_results,
        "has_more": payload.get("has_more"),
        "next_cursor": payload.get("next_cursor"),
    }


def _summarize_notion_page(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": "notion_page_summary_v1",
        "id": payload.get("id"),
        "title": _extract_title_from_notion_page(payload),
        "url": payload.get("url"),
        "created_time": payload.get("created_time"),
        "last_edited_time": payload.get("last_edited_time"),
        "parent": payload.get("parent"),
        "object": payload.get("object"),
    }


def maybe_trim_tool_output(*, tool_name: str, tool_args: Optional[Dict[str, Any]], result: Any) -> Any:
    """
    Return a trimmed version of tool output for specific high-volume tools.

    We only trim Notion MCP tool outputs today.
    """
    if not isinstance(tool_name, str) or not tool_name:
        return result

    if not tool_name.startswith("notionApi_"):
        return result

    enabled = bool(getattr(settings, "tool_output_trimming_enabled", True))
    if not enabled:
        return result

    max_chars = int(getattr(settings, "tool_trim_notion_max_chars", 4000) or 4000)
    max_chars = max(500, min(max_chars, 20000))

    # Many MCP tools return either:
    # - a dict (already JSON)
    # - a JSON string
    # - a list like: [{"type":"text","text":"{...json...}"}]
    raw_obj: Any = result
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict) and first.get("type") == "text" and isinstance(first.get("text"), str):
            maybe = _safe_json_loads(first["text"])
            if maybe is not None:
                raw_obj = maybe
    elif isinstance(result, str):
        maybe = _safe_json_loads(result)
        if maybe is not None:
            raw_obj = maybe

    if not isinstance(raw_obj, dict):
        return result

    # Summarize search results
    if tool_name == "notionApi_API-post-search":
        query = None
        if isinstance(tool_args, dict) and isinstance(tool_args.get("query"), str):
            query = tool_args.get("query")
        summary = _summarize_notion_search(raw_obj, query=query)
        out = json.dumps(summary, ensure_ascii=False)
        return _truncate(out, max_chars)

    # Summarize page retrieval
    if tool_name in ("notionApi_API-retrieve-a-page", "notionApi_API-get-page", "notionApi_API-retrieve-page"):
        summary = _summarize_notion_page(raw_obj)
        out = json.dumps(summary, ensure_ascii=False)
        return _truncate(out, max_chars)

    # Default for other Notion tools: do a hard cap if it's a large JSON
    try:
        dumped = json.dumps(raw_obj, ensure_ascii=False)
    except Exception:
        return result
    if len(dumped) > max_chars:
        return _truncate(dumped, max_chars)
    return result



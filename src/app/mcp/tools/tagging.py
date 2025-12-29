"""
Tool tagging helpers for local (non-MCP) tools.

We store tags in BaseTool.metadata (LangChain-native) so the tag travels with the tool
and can be used both for:
- bootstrap categorization (source_server grouping)
- runtime introspection/logging
"""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.tools import BaseTool


def tag_tool(tool: BaseTool, *, source_server: str, extra_metadata: Dict[str, Any] | None = None) -> BaseTool:
    """
    Attach a source_server tag to a tool using LangChain-native metadata.

    This avoids bootstrap mutating tools and makes the tag live with the tool definition.
    """
    meta = dict(getattr(tool, "metadata", None) or {})
    meta["source_server"] = source_server
    if extra_metadata:
        meta.update(extra_metadata)
    tool.metadata = meta

    # Optional: also mirror into tags for easier filtering/debugging.
    tags = list(getattr(tool, "tags", None) or [])
    ss_tag = f"source_server:{source_server}"
    if ss_tag not in tags:
        tags.append(ss_tag)
    tool.tags = tags

    return tool



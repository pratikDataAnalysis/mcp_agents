"""
Local (non-MCP) tool registry.

These tools are implemented in-process (Python) but are treated like "tool sources"
by bootstrap so they can be categorized into agents by the LLM alongside MCP tools.
"""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool

from src.app.mcp.tools.language_tools import get_language_tools


def get_local_tools() -> List[BaseTool]:
    """
    Return all in-process tools that should be loaded at worker bootstrap time.
    """
    tools: List[BaseTool] = []
    tools.extend(get_language_tools())
    return tools



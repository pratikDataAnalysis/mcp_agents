"""
Supervisor tools.

Responsibilities:
- Provide utility tools that the Supervisor can use directly
- These tools are NOT agent-specific
- Used for orchestration / reasoning support

Current tools:
- get_current_datetime
"""

from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.tools import tool

from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


@tool
def get_current_datetime() -> str:
    """
    Returns the current date and time in ISO 8601 format (UTC).

    The Supervisor MUST use this tool whenever:
    - The user request involves time-sensitive information
    - The user asks about "today", "now", "current", etc.
    """
    now = datetime.now(timezone.utc).isoformat()
    logger.debug("Supervisor tool invoked | get_current_datetime=%s", now)
    return now

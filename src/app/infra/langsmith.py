"""
LangSmith / LangChain tracing setup.

We prefer explicit env-driven configuration via `Settings`, but LangChain/LangGraph
ultimately read standard `LANGCHAIN_*` environment variables.
"""

from __future__ import annotations

import os

from src.app.config.settings import settings
from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


def setup_langsmith_tracing() -> None:
    """
    Configure LangSmith tracing using settings -> environment variables.

    Source of truth is ALWAYS `settings` (not the current process environment).
    This is safe to call multiple times.
    """
    enabled = bool(settings.langchain_tracing_v2)

    if enabled:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        if settings.langchain_api_key:
            os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        if settings.langchain_project:
            os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        if settings.langchain_endpoint:
            os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint

        logger.info(
            "LangSmith tracing enabled | project=%s",
            settings.langchain_project or "(default)",
        )
        return

    # Disabled: remove vars to avoid accidental tracing via leftover environment.
    os.environ.pop("LANGCHAIN_TRACING_V2", None)
    os.environ.pop("LANGCHAIN_API_KEY", None)
    os.environ.pop("LANGCHAIN_PROJECT", None)
    os.environ.pop("LANGCHAIN_ENDPOINT", None)
    logger.debug("LangSmith tracing disabled")



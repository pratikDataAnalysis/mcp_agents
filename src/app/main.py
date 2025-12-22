"""
FastAPI service entrypoint.

Responsibilities:
- Create FastAPI app
- Register API routes (WhatsApp, future inputs)
- Load configuration
- Act as a lightweight ingress layer

IMPORTANT:
- This service does NOT create agents or supervisors
- All execution happens in Redis workers
"""

from __future__ import annotations

from fastapi import FastAPI

from src.app.api.whatsapp_webhook import router as whatsapp_router
from src.app.config.settings import settings
from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


def create_app() -> FastAPI:
    """
    FastAPI application factory.
    """
    app = FastAPI(title="MCP WhatsApp Ingress Service")

    # Register routes
    app.include_router(whatsapp_router)

    logger.info(
        "FastAPI ingress service initialized | env=%s",
        settings.app_env,
    )

    return app


# ASGI entrypoint (required by uvicorn)
app = create_app()

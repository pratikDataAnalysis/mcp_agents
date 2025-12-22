"""Central logger configuration.

Why this exists:
- Consistent formatting across all modules
- One place to tune log level/handlers
- Easier debugging for webhook + agent orchestration
"""

import logging
import sys


def setup_logger(name: str = "mcp_whatsapp") -> logging.Logger:
    """Create and return a configured logger.

    NOTE:
    - Keep this simple; avoid hidden global state.
    - Every module should do: `logger = setup_logger(__name__)`.
    """
    logger = logging.getLogger(name)

    # Prevent duplicate handlers in reload environments (uvicorn --reload)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Avoid propagating to root and double-printing
    logger.propagate = False
    return logger

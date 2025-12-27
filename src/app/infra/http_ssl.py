"""
HTTPS SSL helpers.

Why this exists:
- On some local Python installs (notably Homebrew Python on macOS), urllib can fail with:
  SSL: CERTIFICATE_VERIFY_FAILED (unable to get local issuer certificate)

We standardize a single "create_ssl_context()" helper that uses certifi's CA bundle
when available, and otherwise falls back to default SSL context.
"""

from __future__ import annotations

import ssl
from typing import Optional


def create_ssl_context() -> Optional[ssl.SSLContext]:
    """
    Returns an SSLContext configured with certifi CA bundle if available.

    If certifi is not installed, returns None (urllib will use default context).
    """
    try:
        import certifi  # type: ignore
    except Exception:
        return None

    return ssl.create_default_context(cafile=certifi.where())


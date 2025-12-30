"""
Media hosting (ingress-side).

Purpose:
- Serve locally generated media files (e.g., TTS audio) over HTTP so Twilio can fetch them
  as WhatsApp `media_url`.

IMPORTANT:
- Twilio requires a publicly reachable HTTPS URL. In local dev, expose this service via
  ngrok and set MEDIA_PUBLIC_BASE_URL accordingly.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.app.config.settings import settings

router = APIRouter()


def _safe_resolve_under_root(*, root: Path, rel_path: str) -> Path:
    """
    Resolve a user-provided relative path safely under a root directory.
    Prevents path traversal.
    """
    candidate = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if root_resolved == candidate or root_resolved in candidate.parents:
        return candidate
    raise HTTPException(status_code=400, detail="Invalid path")


@router.get("/media/{rel_path:path}")
def get_media(rel_path: str):
    root = Path(settings.media_root_dir)
    path = _safe_resolve_under_root(root=root, rel_path=rel_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)



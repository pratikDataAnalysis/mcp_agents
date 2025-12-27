"""
Twilio WhatsApp audio -> OpenAI STT -> transcript.

This is designed for the worker runtime:
- Download media from Twilio MediaUrl (requires basic auth)
- Convert OGG/OPUS (common for WhatsApp voice notes) to MP3 via ffmpeg
- Call OpenAI audio transcriptions endpoint (Whisper) to get text

NOTE:
- Download and OpenAI HTTP calls are done using stdlib urllib, wrapped in asyncio.to_thread.
- ffmpeg must be available in the worker runtime environment.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import tempfile
from typing import Optional, Tuple
from urllib.request import Request, urlopen

from src.app.config.settings import settings
from src.app.infra.openai_stt import transcribe_audio_file, translate_audio_file_to_english
from src.app.infra.http_ssl import create_ssl_context


def _basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _download_twilio_media_blocking(
    *,
    media_url: str,
    dst_path: str,
    twilio_account_sid: str,
    twilio_auth_token: str,
) -> None:
    """
    Download Twilio MediaUrl to dst_path (blocking).
    """
    req = Request(
        media_url,
        method="GET",
        headers={"Authorization": _basic_auth_header(twilio_account_sid, twilio_auth_token)},
    )

    # urlopen follows redirects by default.
    ssl_ctx = create_ssl_context()
    with urlopen(req, timeout=120, context=ssl_ctx) as resp:
        data = resp.read()

    with open(dst_path, "wb") as f:
        f.write(data)


async def _ffmpeg_convert_to_mp3(src_path: str, dst_path: str) -> None:
    """
    Convert any audio file to mp3 using ffmpeg.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        src_path,
        dst_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = (stderr or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg failed (exit={proc.returncode}): {err}")


def _ext_from_content_type(content_type: Optional[str]) -> str:
    """
    Best-effort extension mapping for Twilio MediaContentType0.

    WhatsApp voice notes typically arrive as audio/ogg (OPUS inside).
    """
    ct = (content_type or "").lower().strip()
    if ct.startswith("audio/ogg"):
        return ".ogg"
    if ct.startswith("audio/opus"):
        return ".opus"
    if ct.startswith("audio/mpeg"):
        return ".mp3"
    if ct.startswith("audio/mp4") or ct.startswith("audio/m4a"):
        return ".m4a"
    if ct.startswith("audio/wav"):
        return ".wav"
    return ".bin"


async def transcribe_twilio_audio(
    *,
    media_url: str,
    content_type: Optional[str] = None,
    twilio_account_sid: str,
    twilio_auth_token: str,
    openai_api_key: str,
    model: str = "whisper-1",
    language: Optional[str] = None,
    keep_debug_files: bool = False,
) -> Tuple[str, str]:
    """
    Returns:
        (transcript_text, debug_dir)

    debug_dir contains the downloaded + converted audio for troubleshooting.
    Caller may delete it after success if desired.
    """
    if not twilio_account_sid or not twilio_auth_token:
        raise ValueError("Twilio credentials missing (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN)")
    if not openai_api_key:
        raise ValueError("OpenAI API key missing (OPENAI_API_KEY)")

    debug_dir = tempfile.mkdtemp(prefix="twilio-audio-")
    raw_ext = _ext_from_content_type(content_type)
    raw_path = os.path.join(debug_dir, f"input_audio{raw_ext}")
    mp3_path = os.path.join(debug_dir, "input_audio.mp3")

    await asyncio.to_thread(
        _download_twilio_media_blocking,
        media_url=media_url,
        dst_path=raw_path,
        twilio_account_sid=twilio_account_sid,
        twilio_auth_token=twilio_auth_token,
    )

    # Optional conversion step:
    # If ffmpeg is available, convert to mp3 for maximum STT compatibility.
    # If ffmpeg is NOT available (common in constrained environments), we fall back
    # to sending the original file to OpenAI STT.
    use_path = raw_path
    if shutil.which("ffmpeg"):
        try:
            await _ffmpeg_convert_to_mp3(raw_path, mp3_path)
            use_path = mp3_path
        except Exception:
            # If conversion fails, still attempt STT on raw file.
            use_path = raw_path

    try:
        # If user requires English always, prefer OpenAI translations endpoint.
        if getattr(settings, "openai_stt_force_english", False):
            result = await asyncio.to_thread(
                translate_audio_file_to_english,
                file_path=use_path,
                api_key=openai_api_key,
                model=model,
                prompt="Return the transcript in English.",
            )
        else:
            result = await asyncio.to_thread(
                transcribe_audio_file,
                file_path=use_path,
                api_key=openai_api_key,
                model=model,
                language=language,
            )
        return result.text, debug_dir
    finally:
        if not keep_debug_files:
            shutil.rmtree(debug_dir, ignore_errors=True)


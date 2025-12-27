"""
OpenAI Speech-to-Text (STT) helper.

Design goals:
- No extra dependency (use stdlib urllib)
- Async-friendly (caller should run blocking parts in a thread)
- Minimal surface area: "transcribe file -> text"
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from dataclasses import dataclass
from typing import Optional
from urllib.request import Request, urlopen

from src.app.config.settings import settings
from src.app.infra.http_ssl import create_ssl_context


OPENAI_TRANSCRIPTIONS_URL = settings.openai_transcriptions_url
OPENAI_TRANSLATIONS_URL = settings.openai_translations_url


@dataclass(frozen=True)
class OpenAITranscriptionResult:
    text: str
    raw: dict


def _guess_mime(filename: str) -> str:
    mt, _ = mimetypes.guess_type(filename)
    return mt or "application/octet-stream"


def _encode_multipart_form(fields: dict, file_field: str, file_path: str) -> tuple[bytes, str]:
    """
    Build multipart/form-data body.
    """
    boundary = f"----mcpAgentBoundary{uuid.uuid4().hex}"
    lines: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        lines.append(value.encode())
        lines.append(b"\r\n")

    for k, v in fields.items():
        if v is None:
            continue
        add_field(k, str(v))

    filename = os.path.basename(file_path)
    file_mime = _guess_mime(filename)
    with open(file_path, "rb") as f:
        data = f.read()

    lines.append(f"--{boundary}\r\n".encode())
    lines.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode()
    )
    lines.append(f"Content-Type: {file_mime}\r\n\r\n".encode())
    lines.append(data)
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode())

    body = b"".join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def transcribe_audio_file(
    *,
    file_path: str,
    api_key: str,
    model: str = "whisper-1",
    language: Optional[str] = None,
    prompt: Optional[str] = None,
) -> OpenAITranscriptionResult:
    """
    Call OpenAI STT (transcriptions) and return the transcript text.

    This is a blocking function (urllib). Call it via asyncio.to_thread(...) from async code.
    """
    if not api_key:
        raise ValueError("OpenAI API key is missing (OPENAI_API_KEY)")

    fields = {
        "model": model,
        "language": language,
        "prompt": prompt,
        "response_format": "json",
    }
    body, content_type = _encode_multipart_form(fields, "file", file_path)

    req = Request(
        OPENAI_TRANSCRIPTIONS_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
        },
    )

    ssl_ctx = create_ssl_context()
    with urlopen(req, timeout=120, context=ssl_ctx) as resp:
        raw_bytes = resp.read()
        payload = json.loads(raw_bytes.decode("utf-8"))

    text = (payload.get("text") or "").strip()
    return OpenAITranscriptionResult(text=text, raw=payload)


def translate_audio_file_to_english(
    *,
    file_path: str,
    api_key: str,
    model: str = "whisper-1",
    prompt: Optional[str] = None,
) -> OpenAITranscriptionResult:
    """
    Call OpenAI STT translations endpoint and return ENGLISH text.

    This is a blocking function (urllib). Call it via asyncio.to_thread(...) from async code.
    """
    if not api_key:
        raise ValueError("OpenAI API key is missing (OPENAI_API_KEY)")

    fields = {
        "model": model,
        "prompt": prompt,
        "response_format": "json",
    }
    body, content_type = _encode_multipart_form(fields, "file", file_path)

    req = Request(
        OPENAI_TRANSLATIONS_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
        },
    )

    ssl_ctx = create_ssl_context()
    with urlopen(req, timeout=120, context=ssl_ctx) as resp:
        raw_bytes = resp.read()
        payload = json.loads(raw_bytes.decode("utf-8"))

    text = (payload.get("text") or "").strip()
    return OpenAITranscriptionResult(text=text, raw=payload)


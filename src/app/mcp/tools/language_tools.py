"""
Language / audio tools (local, non-MCP).

Goals:
- Provide language normalization (any language -> English) for downstream tool-using agents.
- Provide translation (English -> target language, or arbitrary text -> target language).
- Provide basic TTS (text -> speech audio file) for future WhatsApp media replies.

Important delivery note:
- Twilio WhatsApp "audio reply" requires a publicly reachable media URL.
  This tool only generates a local file path; hosting/sending as media is a separate step.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from typing import List, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from langchain_core.tools import BaseTool
from langchain.tools import tool
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from src.app.config.settings import settings
from src.app.infra.http_ssl import create_ssl_context
from src.app.logging.logger import setup_logger
from src.app.mcp.tools.tagging import tag_tool

logger = setup_logger(__name__)

LOCAL_AUDIO_SOURCE_SERVER = "localAudio"

# -----------------------------
# LLM helpers (for detection/translation)
# -----------------------------

class _DetectToEnglishOut(BaseModel):
    detected_language: str = Field(description="Detected language name or ISO code (best effort)")
    english_text: str = Field(description="Translation of the input into English (preserve meaning)")


class _TranslateOut(BaseModel):
    translated_text: str = Field(description="Translated text in the requested target language")


def _build_llm():
    """
    Build a small chat model instance for local tools.

    Note: This is intentionally similar to bootstrap.build_llm_model, but kept local to
    avoid circular imports.
    """
    provider = (settings.llm_provider or "openai").lower()
    resolved_model = settings.llm_model_name or "gpt-4o-mini"
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=resolved_model)
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=resolved_model)
    raise ValueError(f"Unsupported llm_provider={provider!r}. Use 'ollama' or 'openai'.")


def _llm_detect_and_to_english(*, text: str, hint_language: Optional[str] = None) -> _DetectToEnglishOut:
    llm = _build_llm().with_structured_output(_DetectToEnglishOut)
    prompt = (
        "Task: detect the language of the user's text and translate it to English.\n"
        "Rules:\n"
        "- If text is already English, return english_text equal to the input.\n"
        "- Keep meaning and names.\n"
        "- detected_language can be a common language name (e.g., Hindi) or ISO code.\n"
    )
    if hint_language:
        prompt += f"\nHint: the user may be using: {hint_language}\n"
    prompt += f"\nUser text:\n{text}\n"
    return llm.invoke(prompt)


def _llm_translate(*, text: str, target_language: str, source_language: Optional[str] = None) -> _TranslateOut:
    llm = _build_llm().with_structured_output(_TranslateOut)
    prompt = (
        "Task: translate the user's text to the requested target language.\n"
        "Rules:\n"
        "- Preserve meaning and proper nouns.\n"
        "- Return ONLY the translated text (no extra commentary).\n"
        f"- Target language: {target_language}\n"
    )
    if source_language:
        prompt += f"- Source language (hint): {source_language}\n"
    prompt += f"\nText:\n{text}\n"
    return llm.invoke(prompt)


# -----------------------------
# OpenAI TTS (local file output)
# -----------------------------

OPENAI_TTS_URL = settings.openai_tts_url


@dataclass(frozen=True)
class TextToSpeechResult:
    file_path: str
    format: str


def _openai_tts_blocking(*, text: str, voice: str, model: str, fmt: str) -> TextToSpeechResult:
    api_key = settings.openai_api_key or ""
    if not api_key:
        raise ValueError("OpenAI API key is missing (OPENAI_API_KEY)")

    payload = {
        "model": model,
        "voice": voice,
        "input": text,
        "format": fmt,
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        OPENAI_TTS_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    ssl_ctx = create_ssl_context()
    try:
        with urlopen(req, timeout=120, context=ssl_ctx) as resp:
            audio_bytes = resp.read()
    except HTTPError as e:
        # Include response body to help debug model/url issues (common cause of 404).
        try:
            body = (e.read() or b"").decode("utf-8", errors="replace")
        except Exception:
            body = ""
        raise ToolException(f"OpenAI TTS failed | status={getattr(e, 'code', None)} | body={body}") from e

    out_dir = tempfile.mkdtemp(prefix="tts-")
    out_path = os.path.join(out_dir, f"speech-{uuid.uuid4().hex}.{fmt}")
    with open(out_path, "wb") as f:
        f.write(audio_bytes)

    return TextToSpeechResult(file_path=out_path, format=fmt)


# -----------------------------
# Public tools (loaded into agents)
# -----------------------------

class DetectToEnglishInput(BaseModel):
    text: str = Field(description="Input text in any language")
    hint_language: Optional[str] = Field(default=None, description="Optional hint about source language")


@tool(name_or_callable="localAudio_detect_and_translate_to_english", args_schema=DetectToEnglishInput)
def localAudio_detect_and_translate_to_english(text: str, hint_language: Optional[str] = None) -> dict:
    """
    Detect input language and translate to English.

    Returns:
      { "detected_language": "...", "english_text": "..." }
    """
    out = _llm_detect_and_to_english(text=text, hint_language=hint_language)
    return out.model_dump()


class TranslateTextInput(BaseModel):
    text: str = Field(description="Text to translate")
    target_language: str = Field(description="Target language (e.g., 'Hindi', 'es', 'French')")
    source_language: Optional[str] = Field(default=None, description="Optional hint about source language")


@tool(name_or_callable="localAudio_translate_text", args_schema=TranslateTextInput)
def localAudio_translate_text(text: str, target_language: str, source_language: Optional[str] = None) -> str:
    """
    Translate text to a target language. Returns the translated text only.
    """
    out = _llm_translate(text=text, target_language=target_language, source_language=source_language)
    return out.translated_text


class TextToSpeechInput(BaseModel):
    text: str = Field(description="Text to synthesize as speech")
    voice: str = Field(default_factory=lambda: settings.tts_voice, description="OpenAI voice name (e.g., alloy)")
    model: str = Field(default_factory=lambda: settings.tts_model_name, description="OpenAI TTS model name")
    format: str = Field(default_factory=lambda: settings.tts_format, description="Audio format (mp3, wav, etc.)")


@tool(name_or_callable="localAudio_text_to_speech", args_schema=TextToSpeechInput)
async def localAudio_text_to_speech(
    text: str,
    voice: str = "alloy",
    model: str = "tts-1",
    format: str = "mp3",
) -> dict:
    """
    Convert text into a speech audio file (saved locally).

    Returns:
      { "file_path": "...", "format": "mp3" }
    """
    # Keep it event-loop-safe: run blocking HTTP in a background thread.
    result = await asyncio.to_thread(_openai_tts_blocking, text=text, voice=voice, model=model, fmt=format)
    return {"file_path": result.file_path, "format": result.format}


# Tag tools at definition time so source_server lives with the tool itself.
localAudio_detect_and_translate_to_english = tag_tool(
    localAudio_detect_and_translate_to_english,
    source_server=LOCAL_AUDIO_SOURCE_SERVER,
)
localAudio_translate_text = tag_tool(
    localAudio_translate_text,
    source_server=LOCAL_AUDIO_SOURCE_SERVER,
)
localAudio_text_to_speech = tag_tool(
    localAudio_text_to_speech,
    source_server=LOCAL_AUDIO_SOURCE_SERVER,
)

# Tool error handling: do not crash the whole supervisor run if TTS fails.
localAudio_text_to_speech.handle_tool_error = True


def get_language_tools() -> List[BaseTool]:
    """
    Export all local language tools for bootstrap loading.
    """
    return [
        localAudio_detect_and_translate_to_english,
        localAudio_translate_text,
        localAudio_text_to_speech,
    ]



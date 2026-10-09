"""The Agent's voice: speech-to-text and text-to-speech through Groq (OpenAI-compatible audio API)."""
from __future__ import annotations

import base64
import logging
from typing import Dict, Optional

import httpx

from app.agent.errors import ExternalServiceError, NotConfiguredError
from app.config import settings
from app.core.metrics import metrics

logger = logging.getLogger("call_center")

GROQ_BASE = "https://api.groq.com/openai/v1"


def _auth() -> Dict[str, str]:
    if not settings.GROQ_API_KEY:
        raise NotConfiguredError("GROQ_API_KEY is not set")
    return {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}


def transcribe(audio: bytes, filename: str = "voice-message.webm", content_type: Optional[str] = None) -> str:
    headers = _auth()
    data = {"model": settings.WHISPER_MODEL, "response_format": "json", "temperature": "0"}
    if settings.STT_LANGUAGE:
        data["language"] = settings.STT_LANGUAGE
    files = {"file": (filename, audio, content_type or "application/octet-stream")}
    try:
        with metrics.timed("voice.stt"):
            response = httpx.post(f"{GROQ_BASE}/audio/transcriptions", data=data, files=files,
                                  headers=headers, timeout=60.0)
            response.raise_for_status()
            text = response.json().get("text", "")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Groq transcription failed: %s", exc)
        raise ExternalServiceError("transcription failed") from exc
    return (text or "").strip()


def synthesize(text: str) -> str:
    """Return base64-encoded WAV audio for ``text``."""
    headers = _auth()
    payload = {
        "model": settings.GROQ_TTS_MODEL,
        "voice": settings.GROQ_TTS_VOICE,
        "input": text[:1500],
        "response_format": "wav",
    }
    try:
        with metrics.timed("voice.tts"):
            response = httpx.post(f"{GROQ_BASE}/audio/speech", json=payload, headers=headers, timeout=60.0)
            response.raise_for_status()
            audio = response.content
    except httpx.HTTPError as exc:
        logger.warning("Groq TTS failed: %s", exc)
        raise ExternalServiceError("speech synthesis failed") from exc
    if not audio:
        raise ExternalServiceError("speech synthesis returned no audio")
    return base64.b64encode(audio).decode("ascii")

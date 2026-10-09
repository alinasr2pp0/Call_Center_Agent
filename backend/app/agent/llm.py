"""Core LLM orchestration via OpenRouter, with Tavily-powered web-search fallback. Speech-to-text (STT) and text-to-speech (TTS) are modularized in `speech.py` using Groq."""

from __future__ import annotations

import logging
import re
from typing import Dict, List

import httpx

from app.agent.errors import ExternalServiceError, NotConfiguredError
from app.config import settings
from app.core.metrics import metrics

logger = logging.getLogger("call_center")

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _headers() -> Dict[str, str]:
    if not settings.OPENROUTER_API_KEY:
        raise NotConfiguredError("OPENROUTER_API_KEY is not set")
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
               "X-Title": settings.APP_NAME}  # optional OpenRouter attribution headers
    if settings.OPENROUTER_REFERER:
        headers["HTTP-Referer"] = settings.OPENROUTER_REFERER
    return headers


# ---------------------------------------------------------------- chat
def chat(messages: List[Dict[str, str]], *, max_tokens: int = 1200, temperature: float = 0.2) -> str:
    headers = _headers()
    payload = {
        "model": settings.OPENROUTER_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        with metrics.timed("api.openrouter.chat_completion"):
            response = httpx.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", json=payload,
                                  headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"] or ""  # an {"error": ...} body raises KeyError
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("OpenRouter chat failed: %s", exc)
        raise ExternalServiceError("LLM request failed") from exc
    return _THINK_BLOCK.sub("", content).strip()


# ---------------------------------------------------------------- web search
def web_search(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    if not settings.TAVILY_API_KEY:
        raise NotConfiguredError("TAVILY_API_KEY is not set")
    try:
        with metrics.timed("api.tavily.search"):
            response = httpx.post(
                "https://api.tavily.com/search",
                json={"query": query[:400], "max_results": max_results, "search_depth": "basic"},
                headers={"Authorization": f"Bearer {settings.TAVILY_API_KEY}"},
                timeout=20.0,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Tavily search failed: %s", exc)
        raise ExternalServiceError("web search failed") from exc
    return [
        {"title": str(r.get("title", ""))[:200], "url": str(r.get("url", "")), "content": str(r.get("content", ""))[:800]}
        for r in results[:max_results]
    ]

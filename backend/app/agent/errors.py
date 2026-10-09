"""Errors shared by the Agent's external providers (LLM, search, speech, phone)."""
from __future__ import annotations


class ExternalServiceError(RuntimeError):
    """An external AI/search/speech/phone provider failed or is not configured."""


class NotConfiguredError(ExternalServiceError):
    """The feature needs an API key that is not set."""

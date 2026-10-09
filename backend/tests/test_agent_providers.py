"""The Agent's providers: OpenRouter for the language model, Groq for speech only (no network used).

    cd backend && python -m unittest discover -s tests -p "test_agent_providers*.py" -v
"""
import dataclasses
import unittest
from unittest import mock

import _env  # noqa: F401  (must be first: sets up the test environment)

from app.agent import llm, speech  # noqa: E402
from app.agent.errors import ExternalServiceError, NotConfiguredError  # noqa: E402
from app.config import settings  # noqa: E402


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload, self.content = payload, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def with_settings(module, **changes):
    return mock.patch.object(module, "settings", dataclasses.replace(settings, **changes))


class OpenRouterTests(unittest.TestCase):
    def test_chat_request_shape_and_think_blocks_removed(self):
        reply = FakeResponse({"choices": [{"message": {"content": "<think>x</think> مرحبا"}}]})
        with with_settings(llm, OPENROUTER_API_KEY="or-key", OPENROUTER_REFERER="https://example.test"), \
                mock.patch.object(llm.httpx, "post", return_value=reply) as post:
            self.assertEqual(llm.chat([{"role": "user", "content": "hi"}]), "مرحبا")
        url = post.call_args.args[0]
        kwargs = post.call_args.kwargs
        self.assertEqual(url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer or-key")
        self.assertEqual(kwargs["headers"]["HTTP-Referer"], "https://example.test")
        self.assertEqual(kwargs["json"]["model"], settings.OPENROUTER_MODEL)
        self.assertIn("max_tokens", kwargs["json"])

    def test_error_body_with_http_200_is_an_external_error(self):
        reply = FakeResponse({"error": {"message": "rate limited", "code": 429}})
        with with_settings(llm, OPENROUTER_API_KEY="or-key"), \
                mock.patch.object(llm.httpx, "post", return_value=reply):
            with self.assertRaises(ExternalServiceError):
                llm.chat([{"role": "user", "content": "hi"}])

    def test_network_failure_is_an_external_error(self):
        with with_settings(llm, OPENROUTER_API_KEY="or-key"), \
                mock.patch.object(llm.httpx, "post", side_effect=llm.httpx.HTTPError("boom")):
            with self.assertRaises(ExternalServiceError):
                llm.chat([])

    def test_missing_key(self):
        with with_settings(llm, OPENROUTER_API_KEY=""):
            with self.assertRaises(NotConfiguredError):
                llm.chat([])


class GroqSpeechTests(unittest.TestCase):
    def test_speech_does_not_need_the_openrouter_key(self):
        changes = dict(OPENROUTER_API_KEY="", GROQ_API_KEY="g-key")
        with with_settings(speech, **changes), mock.patch.object(
                speech.httpx, "post", return_value=FakeResponse({"text": " أهلا "})) as post:
            self.assertEqual(speech.transcribe(b"audio"), "أهلا")
        self.assertTrue(post.call_args.args[0].startswith("https://api.groq.com/"))
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer g-key")

    def test_tts_returns_base64(self):
        with with_settings(speech, GROQ_API_KEY="g-key"), mock.patch.object(
                speech.httpx, "post", return_value=FakeResponse(content=b"RIFF")):
            self.assertEqual(speech.synthesize("مرحبا"), "UklGRg==")

    def test_missing_groq_key(self):
        with with_settings(speech, GROQ_API_KEY=""):
            with self.assertRaises(NotConfiguredError):
                speech.transcribe(b"x")
            with self.assertRaises(NotConfiguredError):
                speech.synthesize("x")


class ConfigFlagsTests(unittest.TestCase):
    def test_flags_are_independent(self):
        both = dataclasses.replace(settings, OPENROUTER_API_KEY="a", GROQ_API_KEY="b")
        only_llm = dataclasses.replace(settings, OPENROUTER_API_KEY="a", GROQ_API_KEY="")
        only_speech = dataclasses.replace(settings, OPENROUTER_API_KEY="", GROQ_API_KEY="b")
        self.assertEqual((both.llm_configured, both.speech_configured), (True, True))
        self.assertEqual((only_llm.llm_configured, only_llm.speech_configured), (True, False))
        self.assertEqual((only_speech.llm_configured, only_speech.speech_configured), (False, True))


if __name__ == "__main__":
    unittest.main()

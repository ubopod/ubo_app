"""Tests for the provider-error notification classifier."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from ubo_assistant.error_notification import classify_error

if TYPE_CHECKING:
    from pipecat.frames.frames import ErrorFrame


class DeepSeekLLMService:
    """Fake LLM provider service (name drives stage detection)."""


class OpenAIImageGenService:
    """Fake image-generation provider service."""


class DeepgramSTTService:
    """Fake STT provider service."""


class ElevenLabsTTSService:
    """Fake TTS provider service."""


def _frame(error: str, processor: object | None) -> ErrorFrame:
    return cast('ErrorFrame', SimpleNamespace(error=error, processor=processor))


class TestClassifyError(unittest.TestCase):
    """Verify stage labels and friendly messages for common provider errors."""

    def test_402_insufficient_balance(self) -> None:
        """A 402 from an LLM service maps to the insufficient-balance message."""
        result = classify_error(
            _frame(
                "Error during completion: Error code: 402 - {'error': "
                "{'message': 'Insufficient Balance', 'type': 'unknown_error'}}",
                DeepSeekLLMService(),
            ),
        )
        self.assertEqual(result.title, 'Language model provider error')  # noqa: PT009
        self.assertIn('Insufficient balance', result.content)  # noqa: PT009

    def test_401_authentication(self) -> None:
        """A 401 from an STT service maps to the authentication message."""
        result = classify_error(
            _frame('Error code: 401 - Unauthorized', DeepgramSTTService()),
        )
        self.assertEqual(result.title, 'Speech-to-text provider error')  # noqa: PT009
        self.assertIn('Authentication failed', result.content)  # noqa: PT009

    def test_429_rate_limit(self) -> None:
        """A 429 from a TTS service maps to the rate-limit message."""
        result = classify_error(
            _frame('Error code: 429 - Too Many Requests', ElevenLabsTTSService()),
        )
        self.assertEqual(result.title, 'Text-to-speech provider error')  # noqa: PT009
        self.assertIn('Rate limit', result.content)  # noqa: PT009

    def test_500_server_error(self) -> None:
        """Any 5xx code maps to the generic server-error message."""
        result = classify_error(
            _frame('Error code: 503 - Service Unavailable', DeepSeekLLMService()),
        )
        self.assertIn('server error', result.content)  # noqa: PT009

    def test_no_code_falls_back_to_provider_message(self) -> None:
        """With no status code, the provider's own message is surfaced."""
        result = classify_error(
            _frame(
                "Something failed - {'message': 'Model is overloaded'}",
                DeepSeekLLMService(),
            ),
        )
        self.assertEqual(result.content, 'Model is overloaded')  # noqa: PT009

    def test_message_with_inner_quotes_is_not_truncated(self) -> None:
        """A double-quoted message containing apostrophes is captured whole.

        Regression: the OpenAI 400 ``"The model 'dall-e-3' does not exist."``
        was truncated to ``"The model"`` because the capture stopped at the
        first inner quote.
        """
        result = classify_error(
            _frame(
                'Error processing frame: Error code: 400 - '
                '{\'error\': {\'message\': "The model \'dall-e-3\' does not '
                'exist.", \'type\': \'image_generation_user_error\'}}',
                OpenAIImageGenService(),
            ),
        )
        self.assertEqual(result.title, 'Image generator provider error')  # noqa: PT009
        self.assertEqual(  # noqa: PT009
            result.content,
            "The model 'dall-e-3' does not exist.",
        )

    def test_unknown_processor_uses_generic_stage(self) -> None:
        """An unrecognised/absent processor falls back to the Assistant stage."""
        result = classify_error(_frame('boom', None))
        self.assertEqual(result.title, 'Assistant provider error')  # noqa: PT009
        self.assertEqual(result.content, 'boom')  # noqa: PT009


if __name__ == '__main__':
    unittest.main()

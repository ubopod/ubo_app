"""Tests for the provider-error notification classifier."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.frames import Close, CloseCode

from ubo_assistant.error_notification import classify_error, is_transient_error

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


def _frame(
    error: str,
    processor: object | None,
    exception: Exception | None = None,
) -> ErrorFrame:
    return cast(
        'ErrorFrame',
        SimpleNamespace(error=error, processor=processor, exception=exception),
    )


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


class TestTransientErrorFilter(unittest.TestCase):
    """Recoverable streaming-teardown errors are suppressed from notifications."""

    def test_streaming_timeout_is_transient(self) -> None:
        """Mistral realtime STT idle timeout is filtered out."""
        frame = _frame(
            'Mistral STT error: Timeout waiting for response from streaming '
            'transcription.',
            DeepgramSTTService(),
        )
        self.assertTrue(is_transient_error(frame))  # noqa: PT009

    def test_websocket_1011_upstream_is_transient(self) -> None:
        """A 1011 upstream-connection websocket close is filtered out."""
        frame = _frame(
            'Mistral STT receive error: received 1011 (internal error) '
            'Upstream connection error; then sent 1011 (internal error) '
            'Upstream connection error',
            DeepgramSTTService(),
        )
        self.assertTrue(is_transient_error(frame))  # noqa: PT009

    def test_genuine_error_is_not_transient(self) -> None:
        """Real, actionable errors (auth/balance) still notify."""
        frame = _frame('Error code: 401 - Unauthorized', DeepgramSTTService())
        self.assertFalse(is_transient_error(frame))  # noqa: PT009


class TestTransientCloseCodes(unittest.TestCase):
    """Websocket teardown is classified by RFC 6455 close code, not by message."""

    def test_abrupt_close_is_transient(self) -> None:
        """The hourly ElevenLabs idle drop (no close handshake) is filtered out.

        Regression: ElevenLabs closes an idle websocket without a close frame
        roughly once an hour. Pipecat reconnects successfully, but its teardown
        still pushes an ``ErrorFrame``, which surfaced as a spurious
        "Text-to-speech provider error" notification on the device.
        """
        exception = ConnectionClosedError(rcvd=None, sent=None)
        frame = _frame(
            f'Unknown error occurred: {exception}',
            ElevenLabsTTSService(),
            exception,
        )
        self.assertTrue(is_transient_error(frame))  # noqa: PT009

    def test_going_away_close_is_transient(self) -> None:
        """The same idle drop announced politely, with a full close handshake.

        Regression: after 1006 was suppressed, ub-d7 kept notifying roughly
        hourly with ``received 1001 (going away); then sent 1001 (going away)``
        — ElevenLabs retiring an idle socket via the handshake instead of
        dropping it. Every occurrence was followed within ~200ms by
        ``reconnected successfully on attempt 1``.

        Note this arrives as ``ConnectionClosedOK``, not ``…Error``: websockets
        reserves the error subclass for codes other than 1000/1001. The
        ``isinstance`` check in ``is_transient_error`` is against their shared
        ``ConnectionClosed`` base for exactly this reason.

        The device logs both halves of the handshake ("received 1001 (going
        away); then sent 1001 (going away)"), but only ``rcvd`` is constructed
        here: ``is_transient_error`` reads ``rcvd or sent``, so the received
        half is what classifies, and the keyword needed to set both
        (``rcvd_then_sent``) does not exist in the locked websockets 13.1.
        """
        exception = ConnectionClosedOK(
            rcvd=Close(CloseCode.GOING_AWAY, ''),
            sent=None,
        )
        frame = _frame(
            f'Unknown error occurred: {exception}',
            ElevenLabsTTSService(),
            exception,
        )
        self.assertTrue(is_transient_error(frame))  # noqa: PT009

    def test_internal_error_close_is_transient(self) -> None:
        """A 1011 close from the provider is infrastructure noise."""
        exception = ConnectionClosedError(
            rcvd=Close(CloseCode.INTERNAL_ERROR, ''),
            sent=None,
        )
        frame = _frame('receive error', DeepgramSTTService(), exception)
        self.assertTrue(is_transient_error(frame))  # noqa: PT009

    def test_try_again_later_close_is_transient(self) -> None:
        """A 1013 close explicitly asks us to retry."""
        exception = ConnectionClosedError(
            rcvd=Close(CloseCode.TRY_AGAIN_LATER, ''),
            sent=None,
        )
        frame = _frame('receive error', ElevenLabsTTSService(), exception)
        self.assertTrue(is_transient_error(frame))  # noqa: PT009

    def test_policy_violation_close_is_not_transient(self) -> None:
        """A 1008 close is a real config problem and must still notify."""
        exception = ConnectionClosedError(
            rcvd=Close(CloseCode.POLICY_VIOLATION, 'invalid context'),
            sent=None,
        )
        frame = _frame('receive error', ElevenLabsTTSService(), exception)
        self.assertFalse(is_transient_error(frame))  # noqa: PT009


class TestUnrecoveredFailuresStillNotify(unittest.TestCase):
    """Pipecat's give-up messages carry no exception and match neither tier.

    These are what a genuine outage looks like once reconnection has been
    exhausted, so suppressing the teardown noise above must not swallow them.
    """

    def test_reconnection_attempt_failed(self) -> None:
        """A failed reconnect attempt notifies."""
        frame = _frame(
            'ElevenLabsTTSService#0 reconnection attempt 3 failed: '
            'websocket reconnection failed verification',
            ElevenLabsTTSService(),
        )
        self.assertFalse(is_transient_error(frame))  # noqa: PT009

    def test_reconnection_exhausted(self) -> None:
        """Exhausting all reconnect attempts notifies."""
        frame = _frame(
            'ElevenLabsTTSService#0 failed to reconnect after 3 attempts',
            ElevenLabsTTSService(),
        )
        self.assertFalse(is_transient_error(frame))  # noqa: PT009

    def test_repeated_quick_failures(self) -> None:
        """Connections dying immediately (e.g. bad key) notify."""
        frame = _frame(
            'ElevenLabsTTSService#0 connection failed 3 times immediately '
            'after connecting',
            ElevenLabsTTSService(),
        )
        self.assertFalse(is_transient_error(frame))  # noqa: PT009

    def test_websocket_unavailable(self) -> None:
        """TTS skipped because the socket never came back notifies."""
        frame = _frame('websocket unavailable', ElevenLabsTTSService())
        self.assertFalse(is_transient_error(frame))  # noqa: PT009


if __name__ == '__main__':
    unittest.main()

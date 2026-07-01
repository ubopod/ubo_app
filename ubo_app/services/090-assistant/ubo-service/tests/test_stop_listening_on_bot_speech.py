"""Tests for the stop-listening-on-bot-speech FrameProcessor.

Verifies that ``StopListeningOnBotSpeech`` dispatches an
``AssistantStopListeningAction`` exactly when a ``BotStartedSpeakingFrame``
arrives while listening, and stays inert otherwise.
"""

from __future__ import annotations

import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from ubo_assistant.stop_listening_on_bot_speech import StopListeningOnBotSpeech


class _Result:
    """Minimal stand-in for the autorun result objects exposing ``.value``."""

    def __init__(self, *, value: bool) -> None:
        """Store *value* as the underlying state field."""
        self.value = value


class _FakeClient:
    """Minimal client surface used by the stop-listening-on-bot-speech tests."""

    def __init__(self) -> None:
        """Capture the autorun callback and expose a dispatch mock."""
        self.callback: Any = None
        self.unsubscribe = MagicMock()
        self.dispatch = MagicMock()

    def autorun(self, selectors: list[str]) -> Any:  # noqa: ANN401
        """Return a registrar that captures the subscriber callback."""
        _ = selectors

        def register(callback: Any) -> Any:  # noqa: ANN401
            self.callback = callback
            return self.unsubscribe

        return register


def _build() -> tuple[StopListeningOnBotSpeech, _FakeClient]:
    client = _FakeClient()
    processor = StopListeningOnBotSpeech(client=cast('Any', client))
    return processor, client


class StopListeningOnBotSpeechTests(unittest.IsolatedAsyncioTestCase):
    """Behavioural tests for the stop-listening-on-bot-speech processor."""

    async def test_bot_started_while_listening_dispatches_stop(self) -> None:
        """BotStartedSpeakingFrame while listening dispatches a stop once."""
        processor, client = _build()
        client.callback([_Result(value=True)])  # is_listening = True

        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            StopListeningOnBotSpeech,
            'push_frame',
            new=AsyncMock(),
        ):
            await processor.process_frame(
                BotStartedSpeakingFrame(),
                FrameDirection.UPSTREAM,
            )

        self.assertEqual(client.dispatch.call_count, 1)  # noqa: PT009
        action = client.dispatch.call_args.kwargs['action']
        reason = action.assistant_stop_listening_action.reason
        # The oneof must carry the bot-started-speaking variant.
        self.assertTrue(  # noqa: PT009
            reason.bot_started_speaking_stop_reason is not None,
        )

    async def test_bot_started_while_not_listening_is_inert(self) -> None:
        """No dispatch when the bot starts speaking but nothing is listening."""
        processor, client = _build()
        client.callback([_Result(value=False)])  # is_listening = False

        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            StopListeningOnBotSpeech,
            'push_frame',
            new=AsyncMock(),
        ):
            await processor.process_frame(
                BotStartedSpeakingFrame(),
                FrameDirection.UPSTREAM,
            )

        self.assertEqual(client.dispatch.call_count, 0)  # noqa: PT009

    async def test_other_frame_while_listening_is_inert(self) -> None:
        """A non-bot-start frame is forwarded but triggers no dispatch."""
        processor, client = _build()
        client.callback([_Result(value=True)])  # is_listening = True

        push_frame = AsyncMock()
        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            StopListeningOnBotSpeech,
            'push_frame',
            new=push_frame,
        ):
            await processor.process_frame(
                BotStoppedSpeakingFrame(),
                FrameDirection.UPSTREAM,
            )

        self.assertEqual(client.dispatch.call_count, 0)  # noqa: PT009
        push_frame.assert_awaited_once()

    async def test_tts_started_frame_dispatches_stop(self) -> None:
        """The earliest TTSStartedFrame triggers the stop while listening."""
        processor, client = _build()
        client.callback([_Result(value=True)])  # is_listening = True

        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            StopListeningOnBotSpeech,
            'push_frame',
            new=AsyncMock(),
        ):
            await processor.process_frame(
                TTSStartedFrame(),
                FrameDirection.DOWNSTREAM,
            )

        self.assertEqual(client.dispatch.call_count, 1)  # noqa: PT009

    async def test_multiple_bot_speech_frames_dispatch_once(self) -> None:
        """The per-session latch collapses a burst of TTS frames to one stop."""
        processor, client = _build()
        client.callback([_Result(value=True)])  # is_listening = True

        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            StopListeningOnBotSpeech,
            'push_frame',
            new=AsyncMock(),
        ):
            await processor.process_frame(
                TTSStartedFrame(),
                FrameDirection.DOWNSTREAM,
            )
            await processor.process_frame(
                TTSAudioRawFrame(b'\x00\x00', 16000, 1),
                FrameDirection.DOWNSTREAM,
            )
            await processor.process_frame(
                BotStartedSpeakingFrame(),
                FrameDirection.UPSTREAM,
            )

        self.assertEqual(client.dispatch.call_count, 1)  # noqa: PT009

    async def test_latch_resets_on_new_listening_session(self) -> None:
        """After listening resumes, the next bot turn dispatches again."""
        processor, client = _build()

        with patch.object(
            FrameProcessor,
            'process_frame',
            new=AsyncMock(),
        ), patch.object(
            StopListeningOnBotSpeech,
            'push_frame',
            new=AsyncMock(),
        ):
            client.callback([_Result(value=True)])  # session 1
            await processor.process_frame(
                TTSStartedFrame(),
                FrameDirection.DOWNSTREAM,
            )
            client.callback([_Result(value=False)])  # stop dispatched
            client.callback([_Result(value=True)])  # session 2 (re-triggered)
            await processor.process_frame(
                TTSStartedFrame(),
                FrameDirection.DOWNSTREAM,
            )

        self.assertEqual(client.dispatch.call_count, 2)  # noqa: PT009

    async def test_cleanup_unsubscribes(self) -> None:
        """Cleanup invokes the unsubscribe callable returned by autorun."""
        processor, client = _build()

        with patch.object(
            StopListeningOnBotSpeech.__mro__[1],
            'cleanup',
            new=AsyncMock(),
        ):
            await processor.cleanup()

        client.unsubscribe.assert_called_once()


if __name__ == '__main__':
    unittest.main()

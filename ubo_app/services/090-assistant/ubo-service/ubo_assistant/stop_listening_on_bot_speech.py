"""Stop listening the instant the bot starts speaking.

The device has no acoustic echo cancellation, so an open mic during TTS
playback captures the bot's own speech and confuses the pipeline. This
pass-through ``FrameProcessor`` watches for the earliest "the bot is talking"
signal — the first ``TTSStartedFrame`` (falling back to the first audio frame or
the transport's ``BotStartedSpeakingFrame``) — and dispatches an
``AssistantStopListeningAction`` so the listening session ends before the bot
can hear itself.

Barge-in is unaffected: it is detected by the always-on wake-word engine in the
speech-recognition service (which reads the system mic independent of
``is_listening``), not by this pipeline's input transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from ubo_bindings.ubo.v1 import (
    Action,
    AssistantStopListeningAction,
    AssistantStopReasonUnion,
    BotStartedSpeakingStopReason,
)

if TYPE_CHECKING:
    from pipecat.frames.frames import Frame
    from ubo_bindings.client import UboRPCClient

# The earliest frames that mean "the assistant is now talking". TTSStartedFrame
# is emitted before any audio is synthesized; the audio/transport frames are
# fallbacks for TTS providers that don't emit it.
_BOT_SPEECH_START_FRAMES = (
    TTSStartedFrame,
    TTSAudioRawFrame,
    BotStartedSpeakingFrame,
)


class StopListeningOnBotSpeech(FrameProcessor):
    """Pass-through FrameProcessor that stops listening when the bot speaks.

    Tracks ``state.assistant.is_listening`` via an autorun so the stop is only
    dispatched when a listening session is actually active. A per-session latch
    closes the race where several bot-speech frames arrive before the
    ``AssistantStopListeningAction`` round-trips and flips ``is_listening``.
    Frames flow through unchanged.
    """

    def __init__(self, *, client: UboRPCClient) -> None:
        """Wire the processor to its UBO RPC client and listening-state autorun."""
        super().__init__()
        self._client = client
        self._is_listening = False
        self._stopped_for_session = False
        self._unsubscribe = client.autorun(['state.assistant.is_listening'])(
            self._on_listening_state_changed,
        )

    def _on_listening_state_changed(self, results: list) -> None:
        """Mirror ``is_listening`` and reset the latch when a session starts."""
        is_listening = bool(results[0].value) if results else False
        if is_listening and not self._is_listening:
            self._stopped_for_session = False
        self._is_listening = is_listening

    async def process_frame(
        self,
        frame: Frame,
        direction: FrameDirection,
    ) -> None:
        """Dispatch a stop on the first bot-speech frame, then forward."""
        await super().process_frame(frame, direction)

        if (
            isinstance(frame, _BOT_SPEECH_START_FRAMES)
            and self._is_listening
            and not self._stopped_for_session
        ):
            self._stopped_for_session = True
            logger.info(
                'Bot started speaking while listening; '
                'dispatching AssistantStopListeningAction to silence the mic',
            )
            self._client.dispatch(
                action=Action(
                    assistant_stop_listening_action=AssistantStopListeningAction(
                        reason=AssistantStopReasonUnion(
                            bot_started_speaking_stop_reason=(
                                BotStartedSpeakingStopReason()
                            ),
                        ),
                    ),
                ),
            )

        await self.push_frame(frame, direction)

    async def cleanup(self) -> None:
        """Unsubscribe from the autorun subscription on teardown."""
        try:
            self._unsubscribe()
        except Exception:  # pragma: no cover - defensive
            logger.exception('Error unsubscribing StopListeningOnBotSpeech')
        await super().cleanup()

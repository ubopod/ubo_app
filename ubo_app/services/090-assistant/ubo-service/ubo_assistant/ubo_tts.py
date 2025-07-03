"""TTS service that wraps multiple TTS services allowing switching between them."""

from collections.abc import AsyncGenerator

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.google.tts import GoogleTTSService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.services.tts_service import TTSService
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    AssistanceAudioFrame,
    AudioSample,
)

from ubo_assistant.piper import PiperTTSService
from ubo_assistant.switch import UboSwitchService


class UboTTSService(UboSwitchService[TTSService], TTSService):
    """TTS service that wraps multiple TTS services allowing switching between them."""

    def __init__(
        self,
        client: UboRPCClient,
        *,
        google_credentials: str | None,
        openai_api_key: str | None,
        **kwargs: object,
    ) -> None:
        """Initialize the TTS service with Google, OpenAI, and Piper TTS services."""
        try:
            if google_credentials:
                self.google_tts = GoogleTTSService(credentials=google_credentials)
            else:
                self.google_tts = None
        except Exception as exception:
            logger.exception(
                'Error while initializing Google TTS',
                extra={'exception': exception},
            )
            self.google_tts = None

        try:
            if openai_api_key:
                self.openai_tts = OpenAITTSService(api_key=openai_api_key)
            else:
                self.openai_tts = None
        except Exception as exception:
            logger.exception(
                'Error while initializing OpenAI TTS',
                extra={'exception': exception},
            )
            self.openai_tts = None

        try:
            self.piper_tts = PiperTTSService()
        except Exception as exception:
            logger.exception(
                'Error while initializing Piper TTS',
                extra={'exception': exception},
            )
            self.piper_tts = None

        self._services = [self.google_tts, self.openai_tts, self.piper_tts]

        super().__init__(
            client=client,
            model='',
            base_url='',
            api_key='',
            **kwargs,
        )

    async def run_tts(self, text: str) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Run TTS on the given text and yield frames."""
        _ = text
        yield None

    async def push_frame(
        self,
        frame: Frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> None:
        """Dispatch the frame in ubo-app's redux bus if it's audio, image or text."""
        await super().push_frame(frame, direction)

        if isinstance(frame, TTSStartedFrame):
            self._reset_assistance()

        if isinstance(frame, TTSAudioRawFrame):
            self._report_assistance_frame(
                AcceptableAssistanceFrame(
                    assistance_audio_frame=AssistanceAudioFrame(
                        audio=AudioSample(
                            data=frame.audio,
                            channels=frame.num_channels,
                            rate=frame.sample_rate,
                            width=2,
                        ),
                        timestamp=self.client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._assistance_index,
                    ),
                ),
            )

        if isinstance(frame, TTSStoppedFrame):
            self._report_assistance_frame(
                AcceptableAssistanceFrame(
                    assistance_audio_frame=AssistanceAudioFrame(
                        audio=None,
                        timestamp=self.client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._assistance_index,
                    ),
                ),
            )

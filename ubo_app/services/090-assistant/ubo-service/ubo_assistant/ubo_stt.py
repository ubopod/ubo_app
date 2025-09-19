"""STT service that wraps multiple STT services allowing switching between them."""

from collections.abc import AsyncGenerator

from loguru import logger
from pipecat.frames.frames import (
    EmulateUserStartedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.assemblyai.stt import (
    AssemblyAIConnectionParams,
    AssemblyAISTTService,
)
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.google.stt import GoogleSTTService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.stt_service import STTService
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    AssistanceTextFrame,
)

from ubo_assistant.segmented_googlestt import SegmentedGoogleSTTService
from ubo_assistant.switch import UboSwitchService
from ubo_assistant.vosk import VoskSTTService


class UboSTTService(UboSwitchService[STTService], STTService):
    """STT service that wraps multiple STT services allowing switching between them."""

    def __init__(
        self,
        client: UboRPCClient,
        *,
        google_credentials: str | None,
        openai_api_key: str | None,
        deepgram_api_key: str | None,
        assemblyai_api_key: str | None,
        selector: str,
    ) -> None:
        """Initialize the STT service with Google, OpenAI, and Vosk STT services."""
        self._assistance_index = 0
        try:
            if google_credentials:
                self.segmented_google_stt = SegmentedGoogleSTTService(
                    credentials=google_credentials,
                    model='long',
                    sample_rate=16000,
                )
            else:
                self.segmented_google_stt = None
        except Exception:
            logger.exception('Error while initializing Google STT')
            self.segmented_google_stt = None

        try:
            if google_credentials:
                self.google_stt = GoogleSTTService(
                    credentials=google_credentials,
                    model='long',
                    sample_rate=16000,
                )
            else:
                self.google_stt = None
        except Exception:
            logger.exception('Error while initializing Google STT')
            self.google_stt = None

        try:
            if openai_api_key:
                self.openai_stt = OpenAISTTService(api_key=openai_api_key)
            else:
                self.openai_stt = None
        except Exception:
            logger.exception('Error while initializing OpenAI STT')
            self.openai_stt = None

        try:
            self.vosk_stt = VoskSTTService()
        except Exception:
            logger.exception('Error while initializing Vosk STT')
            self.vosk_stt = None

        try:
            if deepgram_api_key:
                self.deepgram_stt = DeepgramSTTService(
                    api_key=deepgram_api_key,
                    live_options=LiveOptions(
                        model='nova-3',
                        language='multi',
                        smart_format=True,
                    ),
                )
            else:
                self.deepgram_stt = None
        except Exception:
            logger.exception('Error while initializing Deepgram STT')
            self.deepgram_stt = None

        try:
            if assemblyai_api_key:
                self.assemblyai_stt = AssemblyAISTTService(
                    api_key=assemblyai_api_key,
                    vad_force_turn_endpoint=False,  # Use AssemblyAI's STT-based turn detection
                    connection_params=AssemblyAIConnectionParams(
                        end_of_turn_confidence_threshold=0.7,  # Default confidence threshold
                        min_end_of_turn_silence_when_confident=160,  # 160ms minimum silence
                        max_turn_silence=2400,  # 2.4s maximum turn silence
                    ),
                )
            else:
                self.assemblyai_stt = None
        except Exception:
            logger.exception('Error while initializing AssemblyAI STT')
            self.assemblyai_stt = None

        self._services = {
            'google_segmented': self.segmented_google_stt,
            'google': self.google_stt,
            'openai': self.openai_stt,
            'vosk': self.vosk_stt,
            'deepgram': self.deepgram_stt,
            'assemblyai': self.assemblyai_stt,
        }

        UboSwitchService.__init__(self, client=client, selector=selector)
        STTService.__init__(self)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Ignore this as child classes will handle audio processing."""
        _ = audio
        yield None

    async def push_frame(
        self,
        frame: Frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> None:
        """Dispatch the frame in ubo-app's redux bus if it's audio, image or text."""
        await super().push_frame(frame, direction)

        if isinstance(frame, EmulateUserStartedSpeakingFrame):
            self._reset_assistance()

        if isinstance(frame, InterimTranscriptionFrame):
            self._report_assistance_frame(
                AcceptableAssistanceFrame(
                    assistance_text_frame=AssistanceTextFrame(
                        text=frame.text,
                        timestamp=self.client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._assistance_index,
                    ),
                ),
            )

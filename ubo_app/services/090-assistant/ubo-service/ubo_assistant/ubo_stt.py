"""STT service that wraps multiple STT services allowing switching between them."""

from collections.abc import AsyncGenerator, Callable  # noqa: I001

from loguru import logger
from deepgram import LiveOptions
from pipecat.frames.frames import (
    EmulateUserStartedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.assemblyai.stt import AssemblyAISTTService
from pipecat.services.assemblyai.models import AssemblyAIConnectionParams
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

    def _initialize_service(
        self,
        service_name: str,
        service_factory: Callable[[], STTService | None],
    ) -> STTService | None:
        """Initialize a STT service with error handling.

        Args:
            service_name: Name of the service for logging
            service_factory: Callable that returns the service instance or None

        Returns:
            Initialized service or None if initialization failed

        """
        try:
            service = service_factory()
            if service is not None:
                logger.info('STT initialized successfully',
                        extra={'service_name': service_name})
            else:
                logger.info('STT not initialized',
                        extra={'service_name': service_name})
        except Exception:
            logger.exception('Error while initializing STT',
                        extra={'service_name': service_name})
            return None
        else:
            return service

    def __init__(  # noqa: PLR0913
        self,
        client: UboRPCClient,
        *,
        google_credentials: str | None = None,
        openai_api_key: str | None = None,
        deepgram_api_key: str | None = None,
        assemblyai_api_key: str | None = None,
        selector: str,
    ) -> None:
        """Initialize the STT service with Google, OpenAI, and Vosk STT services."""
        self._assistance_index = 0

        # Initialize Segmented Google STT
        self.segmented_google_stt = self._initialize_service(
            'Google Segmented',
            lambda: (
                SegmentedGoogleSTTService(
                    credentials=google_credentials,
                    model='long',
                    sample_rate=16000,
                )
                if google_credentials
                else None
            ),
        )

        # Initialize Google STT
        self.google_stt = self._initialize_service(
            'Google',
            lambda: (
                GoogleSTTService(
                    credentials=google_credentials,
                    model='long',
                    sample_rate=16000,
                )
                if google_credentials
                else None
            ),
        )

        # Initialize OpenAI STT
        self.openai_stt = self._initialize_service(
            'OpenAI',
            lambda: OpenAISTTService(api_key=openai_api_key) if \
                    openai_api_key else None,
        )

        # Initialize Vosk STT
        self.vosk_stt = self._initialize_service(
            'Vosk',
            lambda: VoskSTTService() if VoskSTTService else None,
        )

        # Initialize Deepgram STT
        self.deepgram_stt = self._initialize_service(
            'Deepgram',
            lambda: (
                DeepgramSTTService(
                    api_key=deepgram_api_key,
                    live_options=LiveOptions(
                        model='nova-3',
                        language='multi',
                        smart_format=True,
                    ),
                )
                if deepgram_api_key
                else None
            ),
        )

        # Initialize AssemblyAI STT
        self.assemblyai_stt = self._initialize_service(
            'AssemblyAI',
            lambda: (
                AssemblyAISTTService(
                    api_key=assemblyai_api_key,
                    vad_force_turn_endpoint=False,
                    connection_params=AssemblyAIConnectionParams(
                        end_of_turn_confidence_threshold=0.7,
                        min_end_of_turn_silence_when_confident=160,
                        max_turn_silence=2400,
                    ),
                )
                if assemblyai_api_key
                else None
            ),
        )

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

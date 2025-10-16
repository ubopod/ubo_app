"""TTS service that wraps multiple TTS services allowing switching between them."""

from collections.abc import AsyncGenerator, Callable

from loguru import logger
from pipecat.frames.frames import Frame
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.tts import GoogleTTSService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.services.rime.tts import RimeTTSService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from ubo_bindings.client import UboRPCClient

from ubo_assistant.piper import PiperTTSService
from ubo_assistant.switch import UboSwitchService


class UboTTSService(UboSwitchService[TTSService], TTSService):
    """TTS service that wraps multiple TTS services allowing switching between them."""

    def _initialize_service(
        self,
        service_name: str,
        service_factory: Callable[[], TTSService | None],
    ) -> TTSService | None:
        """Initialize a TTS service with error handling.

        Args:
            service_name: Name of the service for logging
            service_factory: Callable that returns the service instance or None

        Returns:
            Initialized service or None if initialization failed

        """
        try:
            service = service_factory()
            if service is not None:
                logger.info('TTS initialized successfully',
                        extra={'service_name': service_name})
            else:
                logger.info('TTS not initialized',
                        extra={'service_name': service_name})
        except Exception:
            logger.exception('Error while initializing TTS',
                        extra={'service_name': service_name})
            return None
        else:
            return service

    def __init__(  # noqa: PLR0913
        self,
        client: UboRPCClient,
        *,
        google_credentials: str | None,
        openai_api_key: str | None,
        elevenlabs_api_key: str | None,
        elevenlabs_voice_id: str | None,
        rime_api_key: str | None,
        selector: str,
    ) -> None:
        """Initialize TTS service with Google, OpenAI, ElevenLabs, Piper, and Rime."""
        # Initialize Google TTS
        self.google_tts = self._initialize_service(
            'Google',
            lambda: GoogleTTSService(credentials=google_credentials) if \
            google_credentials else None,
        )

        # Initialize OpenAI TTS
        self.openai_tts = self._initialize_service(
            'OpenAI',
            lambda: OpenAITTSService(api_key=openai_api_key) if \
                    openai_api_key else None,
        )

        # Initialize ElevenLabs TTS
        self.elevenlabs_tts = self._initialize_service(
            'ElevenLabs',
            lambda: (
                ElevenLabsTTSService(
                    api_key=elevenlabs_api_key,
                    voice_id=elevenlabs_voice_id,
                    sample_rate=24000,
                    model='eleven_turbo_v2_5',
                    enable_logging=True,
                )
                if elevenlabs_api_key and elevenlabs_voice_id
                else None
            ),
        )

        # Initialize Piper TTS
        self.piper_tts = self._initialize_service(
            'Piper',
            lambda: PiperTTSService() if PiperTTSService else None,
        )

        # Initialize Rime TTS
        self.rime_tts = self._initialize_service(
            'Rime',
            lambda: (
                RimeTTSService(
                    api_key=rime_api_key,
                    voice_id='antoine',
                    model='mistv2',
                    params=RimeTTSService.InputParams(
                        language=Language.EN,
                        speed_alpha=1.0,
                        reduce_latency=False,
                        pause_between_brackets=True,
                        phonemize_between_brackets=False,
                    ),
                )
                if rime_api_key
                else None
            ),
        )

        self._services = {
            'google': self.google_tts,
            'openai': self.openai_tts,
            'elevenlabs': self.elevenlabs_tts,
            'piper': self.piper_tts,
            'rime': self.rime_tts,
        }

        UboSwitchService.__init__(self, client=client, selector=selector)
        TTSService.__init__(self)

    async def run_tts(self, text: str) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Run TTS on the given text and yield frames."""
        _ = text
        yield None

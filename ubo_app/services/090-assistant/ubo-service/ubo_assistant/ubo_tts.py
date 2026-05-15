"""TTS service that wraps multiple TTS services allowing switching between them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import Frame
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.tts import GoogleTTSService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.services.rime.tts import RimeTTSService
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language

from ubo_assistant.piper import DEFAULT_PIPER_VOICE_ID, PiperTTSService
from ubo_assistant.switch import UboSwitchService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from betterproto.lib.google.protobuf import StringValue
    from ubo_bindings.client import UboRPCClient


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

        # Initialize Piper TTS with the default voice — the store autorun
        # registered in `_ensure_autoruns_started` reconciles it to the
        # user's persisted voice (it fires once on subscription with the
        # current value, then on every change).
        self.piper_tts = self._initialize_service(
            'Piper',
            lambda: PiperTTSService(voice_id=DEFAULT_PIPER_VOICE_ID)
            if PiperTTSService
            else None,
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

        UboSwitchService.__init__(
            self,
            client=client,
            selector=selector,
            # `voice` is annotated `str | _NotGiven`, but pipecat's docstring
            # says to use None for unsupported fields in store mode and the
            # runtime check (`validate_complete`) only rejects _NotGiven.
            settings=TTSSettings(model=None, voice=None, language=None),  # pyright: ignore[reportArgumentType]
        )

    async def run_tts(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        text: str,
        context_id: str,
    ) -> AsyncGenerator[Frame, None]:
        """Run TTS on the given text and yield frames."""
        _ = text
        _ = context_id
        if False:
            yield Frame()

    def _ensure_autoruns_started(self) -> None:
        """Start the parent autoruns then track the selected Piper voice."""
        if self._autoruns_started:
            return
        super()._ensure_autoruns_started()

        # A store autorun — not an event subscription — is the reliable
        # primitive here: it fires once on registration with the current
        # persisted voice (cold-start) and again on every change, and the
        # client schedules the callback on the pipeline loop itself. The
        # earlier event-based approach hopped from a gRPC callback thread
        # into `create_task`, which raced and silently dropped switches.
        # The callback only records the request; `PiperTTSService.run_tts`
        # does the actual load before each utterance.
        @self.client.autorun(['state.assistant.selected_piper_voice'])
        def _handle_piper_voice_change(data: list[StringValue]) -> None:
            voice_id = data[0].value
            target = self.piper_tts
            if isinstance(target, PiperTTSService):
                target.request_voice(voice_id)

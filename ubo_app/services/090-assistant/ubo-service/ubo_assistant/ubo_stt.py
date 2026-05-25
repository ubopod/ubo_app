"""STT service that wraps multiple STT services allowing switching between them."""

from collections.abc import AsyncGenerator, Callable  # noqa: I001
import os
from dataclasses import dataclass

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    SystemFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.services.assemblyai.stt import AssemblyAISTTService
from pipecat.services.assemblyai.models import AssemblyAIConnectionParams
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.google.stt import GoogleSTTService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import STTService
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    AssistanceTextFrame,
    AssistantPipelineStage,
)

from ubo_assistant.segmented_googlestt import SegmentedGoogleSTTService
from ubo_assistant.switch import UboSwitchService
from ubo_assistant.venice_stt import VeniceSTTService
from ubo_assistant.vosk import DEFAULT_VOSK_MODEL_ID, VoskSTTService

from betterproto.lib.google.protobuf import StringValue

VENICE_BASE_URL = 'https://api.venice.ai/api/v1'
DEFAULT_VENICE_STT_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_STT_MODEL',
    'nvidia/parakeet-tdt-0.6b-v3',
)


@dataclass
class STTServiceConfig:
    """Configuration for cloud STT services.

    Holds the API keys for providers whose underlying real service is built
    on demand by :class:`UboSTTService` whenever the user switches to it.
    Updated by ``_refresh_api_key_service`` so that newly entered keys take
    effect without restarting the subprocess.
    """

    openai_api_key: str | None = None
    deepgram_api_key: str | None = None
    assemblyai_api_key: str | None = None
    venice_api_key: str | None = None


class GenericSTTProxy(STTService):
    """Stable switcher branch for a dynamically refreshed cloud STT service.

    Pipecat 1.0 freezes its service list at ``__init__``; any cloud STT slot
    that starts ``None`` can never come alive later. The proxy is registered
    once at subprocess start and the real underlying service is swapped in
    via :meth:`set_service` the first time the user selects this provider —
    typically right after entering an API key.
    """

    def __init__(self) -> None:
        """Initialize the proxy with no underlying service yet."""
        super().__init__(settings=STTSettings(model=None, language=None))
        self._service: STTService | None = None
        self._processor_setup: FrameProcessorSetup | None = None
        self._start_frame: StartFrame | None = None

    @property
    def service(self) -> STTService | None:
        """Current underlying STT service."""
        return self._service

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Set up the proxy and the current underlying STT, if any."""
        await super().setup(setup)
        self._processor_setup = setup
        if self._service is not None:
            await self._service.setup(setup)

    async def cleanup(self) -> None:
        """Clean up the current underlying STT, if any."""
        if self._service is not None:
            await self._service.cleanup()
        await super().cleanup()

    async def set_service(self, service: STTService | None) -> None:
        """Replace the underlying STT implementation, replaying StartFrame."""
        if self._service is not None:
            await self._service.cleanup()

        self._service = service
        if self._service is None:
            return

        self._service.push_frame = self.push_frame
        if self._processor_setup is not None:
            await self._service.setup(self._processor_setup)
        if self._start_frame is not None:
            await self._service.queue_frame(self._start_frame)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Stub — frames are routed through ``queue_frame`` on the underlying."""
        _ = audio
        yield None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Forward frames to the current underlying STT when configured."""
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self._start_frame = frame
        if self._service is not None:
            await self._service.queue_frame(frame, direction)
        elif isinstance(frame, SystemFrame):
            await self.push_frame(frame, direction)


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

    def __init__(
        self,
        client: UboRPCClient,
        config: STTServiceConfig,
        *,
        google_credentials: str | None = None,
        selector: str,
    ) -> None:
        """Initialize the STT service with Google, OpenAI, and Vosk STT services."""
        self._assistance_index = 0
        self._last_logged_transcription = ''
        self._config = config

        # Initialize Segmented Google STT
        self.segmented_google_stt = self._initialize_service(
            'Google Segmented',
            lambda: (
                SegmentedGoogleSTTService(
                    credentials=google_credentials,
                    sample_rate=16000,
                    settings=GoogleSTTService.Settings(model='long'),
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
                    sample_rate=16000,
                    settings=GoogleSTTService.Settings(model='long'),
                )
                if google_credentials
                else None
            ),
        )

        # Cloud STT providers go behind GenericSTTProxy so they always
        # live in Pipecat's switcher init list. The underlying real
        # Pipecat service is created/refreshed on demand in
        # ``_refresh_api_key_service`` whenever the user switches to
        # that provider — see ``_API_KEY_PROVIDERS`` below.
        self.openai_stt = GenericSTTProxy()
        self.deepgram_stt = GenericSTTProxy()
        self.assemblyai_stt = GenericSTTProxy()
        self.venice_stt = GenericSTTProxy()

        # Initialize Vosk STT with the default model — the store autorun
        # registered in `_ensure_autoruns_started` reconciles it to the
        # user's persisted model id (fires once on subscription with the
        # current value, then on every change).
        self.vosk_stt = self._initialize_service(
            'Vosk',
            lambda: VoskSTTService(model_id=DEFAULT_VOSK_MODEL_ID)
            if VoskSTTService
            else None,
        )

        self._services = {
            'google_segmented': self.segmented_google_stt,
            'google': self.google_stt,
            'openai': self.openai_stt,
            'vosk': self.vosk_stt,
            'deepgram': self.deepgram_stt,
            'assemblyai': self.assemblyai_stt,
            'venice': self.venice_stt,
        }

        UboSwitchService.__init__(
            self,
            client=client,
            selector=selector,
            settings=STTSettings(model=None, language=None),
        )

    # Cloud STT providers whose only runtime input is a single API key.
    # Each entry maps a service id to (env var holding the secret id,
    # config attr storing the value, factory method building the real
    # Pipecat service, proxy attribute on this instance). The proxies are
    # stable members of Pipecat's switcher init list; the underlying real
    # services get created/swapped here when the user picks the provider.
    _API_KEY_PROVIDERS: dict[str, tuple[str, str, str, str]] = {  # noqa: RUF012
        'openai': (
            'OPENAI_API_KEY_SECRET_ID',
            'openai_api_key',
            '_create_openai_service',
            'openai_stt',
        ),
        'deepgram': (
            'DEEPGRAM_API_KEY_SECRET_ID',
            'deepgram_api_key',
            '_create_deepgram_service',
            'deepgram_stt',
        ),
        'assemblyai': (
            'ASSEMBLYAI_API_KEY_SECRET_ID',
            'assemblyai_api_key',
            '_create_assemblyai_service',
            'assemblyai_stt',
        ),
        'venice': (
            'VENICE_API_KEY_SECRET_ID',
            'venice_api_key',
            '_create_venice_service',
            'venice_stt',
        ),
    }

    async def _refresh_api_key_service(self, id: str) -> None:
        """Re-query the API key for *id* and (re)build its underlying service."""
        env_var, config_attr, factory_name, proxy_attr = self._API_KEY_PROVIDERS[id]
        api_key = await self.client.query_secret(os.environ[env_var])
        setattr(self._config, config_attr, api_key)

        factory = getattr(self, factory_name)
        real_service: STTService | None = factory()

        proxy: GenericSTTProxy = getattr(self, proxy_attr)
        if proxy.service is real_service:
            return
        await proxy.set_service(real_service)

        logger.info(
            '{extra} STT service refreshed',
            extra={
                'service_id': id,
                'has_api_key': bool(api_key),
                'has_service': real_service is not None,
            },
        )

    async def set_selected_service(self, id: str) -> None:
        """Set the selected STT service, refreshing the API key first."""
        if id in self._API_KEY_PROVIDERS:
            await self._refresh_api_key_service(id)
        await super().set_selected_service(id)

    def _create_openai_service(self) -> OpenAISTTService | None:
        """Create OpenAI STT service if API key is provided."""
        if not self._config.openai_api_key:
            return None
        try:
            return OpenAISTTService(api_key=self._config.openai_api_key)
        except Exception:
            logger.exception('Error while initializing OpenAI STT')
            return None

    def _create_deepgram_service(self) -> DeepgramSTTService | None:
        """Create Deepgram STT service if API key is provided."""
        if not self._config.deepgram_api_key:
            return None
        try:
            return DeepgramSTTService(
                api_key=self._config.deepgram_api_key,
                settings=DeepgramSTTService.Settings(
                    model='nova-3',
                    language='multi',
                    smart_format=True,
                ),
            )
        except Exception:
            logger.exception('Error while initializing Deepgram STT')
            return None

    def _create_assemblyai_service(self) -> AssemblyAISTTService | None:
        """Create AssemblyAI STT service if API key is provided."""
        if not self._config.assemblyai_api_key:
            return None
        try:
            return AssemblyAISTTService(
                api_key=self._config.assemblyai_api_key,
                vad_force_turn_endpoint=False,
                connection_params=AssemblyAIConnectionParams(
                    end_of_turn_confidence_threshold=0.7,
                    min_end_of_turn_silence_when_confident=160,
                    max_turn_silence=2400,
                ),
            )
        except Exception:
            logger.exception('Error while initializing AssemblyAI STT')
            return None

    def _create_venice_service(self) -> VeniceSTTService | None:
        """Create Venice STT service if API key is provided."""
        if not self._config.venice_api_key:
            return None
        try:
            return VeniceSTTService(
                api_key=self._config.venice_api_key,
                base_url=VENICE_BASE_URL,
                settings=VeniceSTTService.Settings(
                    model=DEFAULT_VENICE_STT_MODEL,
                ),
            )
        except Exception:
            logger.exception('Error while initializing Venice STT')
            return None

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Ignore this as child classes will handle audio processing."""
        _ = audio
        yield None

    def _ensure_autoruns_started(self) -> None:
        """Start the parent autoruns then track the selected Vosk model."""
        if self._autoruns_started:
            return
        super()._ensure_autoruns_started()

        # A store autorun — not an event subscription — is the reliable
        # primitive here: it fires once on registration with the current
        # persisted model id (cold-start) and again on every change. The
        # callback only records the request; ``VoskSTTService.run_stt``
        # does the actual load before each audio chunk.
        @self.client.autorun(['state.assistant.selected_vosk_model'])
        def _handle_vosk_model_change(data: list[StringValue]) -> None:
            model_id = data[0].value
            target = self.vosk_stt
            if isinstance(target, VoskSTTService):
                target.request_model(model_id)

    def _log_transcription(self, text: str) -> None:
        """Log newly transcribed text for assistant debugging."""
        if text == self._last_logged_transcription:
            return
        self._last_logged_transcription = text
        logger.info('STT transcript: {text}', text=text)

    async def push_frame(
        self,
        frame: Frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> None:
        """Dispatch the frame in ubo-app's redux bus if it's audio, image or text."""
        await super().push_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            self._reset_assistance()
            self._last_logged_transcription = ''

        if isinstance(frame, InterimTranscriptionFrame):
            self._log_transcription(frame.text)
            self._report_assistance_frame(
                AcceptableAssistanceFrame(
                    assistance_text_frame=AssistanceTextFrame(
                        text=frame.text,
                        timestamp=self.client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._assistance_index,
                        source=AssistantPipelineStage.STT,
                    ),
                ),
            )
        elif isinstance(frame, TranscriptionFrame):
            self._log_transcription(frame.text)
            # The final transcript — authoritative; `is_last_frame` marks the
            # user turn as complete for consumers building a conversation.
            self._report_assistance_frame(
                AcceptableAssistanceFrame(
                    assistance_text_frame=AssistanceTextFrame(
                        text=frame.text,
                        timestamp=self.client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._assistance_index,
                        source=AssistantPipelineStage.STT,
                        is_last_frame=True,
                    ),
                ),
            )

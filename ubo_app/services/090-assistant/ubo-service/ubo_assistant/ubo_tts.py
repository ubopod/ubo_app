"""TTS service that wraps multiple TTS services allowing switching between them."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from loguru import logger
from pipecat.frames.frames import Frame, StartFrame, SystemFrame
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.tts import GoogleTTSService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.services.rime.tts import RimeTTSService
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from ubo_bindings.ubo.v1 import (
    AssistantTtsName,
    AssistantVoiceChangedEvent,
    Event,
)

from ubo_assistant.kokoro import (
    DEFAULT_KOKORO_VOICE_ID,
    KokoroTTSService,
)
from ubo_assistant.kokoro import MODEL_PATH as KOKORO_MODEL_PATH
from ubo_assistant.kokoro import VOICES_PATH as KOKORO_VOICES_PATH
from ubo_assistant.piper import DEFAULT_PIPER_VOICE_ID, PiperTTSService
from ubo_assistant.switch import UboSwitchService
from ubo_assistant.tts_voice import google_voice_kwargs, rime_language
from ubo_assistant.venice_tts import VeniceTTSService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from betterproto.lib.google.protobuf import StringValue
    from pipecat.pipeline.service_switcher import ServiceSwitcher
    from pipecat.processors.frame_processor import (
        FrameDirection,
        FrameProcessorSetup,
    )
    from ubo_bindings.client import UboRPCClient

# Cloud TTS provider id keyed by the proto ``AssistantTtsName`` enum. Only the
# cloud providers that carry a selectable voice appear here.
_SERVICE_ID_BY_TTS_NAME: dict[AssistantTtsName, str] = {
    AssistantTtsName.GOOGLE: 'google',
    AssistantTtsName.OPENAI: 'openai',
    AssistantTtsName.ELEVENLABS: 'elevenlabs',
    AssistantTtsName.RIME: 'rime',
    AssistantTtsName.VENICE: 'venice',
}

# Per-provider default voice used when the user hasn't picked one. Mirrors
# ``DEFAULT_VOICES`` on the core side (ElevenLabs falls back to its secret).
_DEFAULT_CLOUD_VOICE: dict[str, str] = {
    'openai': 'alloy',
    'rime': 'antoine',
}

VENICE_BASE_URL = 'https://api.venice.ai/api/v1'
DEFAULT_VENICE_TTS_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_TTS_MODEL',
    'tts-kokoro',
)
DEFAULT_VENICE_TTS_VOICE = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_TTS_VOICE',
    # Kept in sync with core's ``DEFAULT_VENICE_TTS_VOICE``.
    'af_heart',
)


@dataclass
class TTSServiceConfig:
    """Configuration for cloud TTS services.

    Holds the credentials for providers whose underlying real service is
    built on demand by :class:`UboTTSService` whenever the user switches
    to it. Updated by ``_refresh_api_key_service`` so that newly entered
    keys take effect without restarting the subprocess.
    """

    openai_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    rime_api_key: str | None = None
    venice_api_key: str | None = None
    google_credentials: str | None = None
    # Per-provider selected voice id, seeded from on-disk state via the
    # cold-start replay of ``AssistantVoiceChangedEvent`` and updated on every
    # change. A dict can't cross a gRPC autorun selector, hence the event.
    selected_voices: dict[str, str] = field(default_factory=dict)


class GenericTTSProxy(TTSService):
    """Stable switcher branch for a dynamically refreshed cloud TTS service.

    Pipecat 1.0 freezes its service list at ``__init__``; any cloud TTS slot
    that starts ``None`` can never come alive later. The proxy is registered
    once at subprocess start and the real underlying service is swapped in
    via :meth:`set_service` the first time the user selects this provider —
    typically right after entering an API key.
    """

    def __init__(self) -> None:
        """Initialize the proxy with no underlying service yet."""
        # `voice` is annotated `str | _NotGiven`, but Pipecat treats None as
        # "unset" in store mode and the runtime check only rejects _NotGiven.
        super().__init__(
            settings=TTSSettings(model=None, voice=None, language=None),  # pyright: ignore[reportArgumentType]
        )
        self._service: TTSService | None = None
        self._processor_setup: FrameProcessorSetup | None = None
        self._start_frame: StartFrame | None = None

    @property
    def service(self) -> TTSService | None:
        """Current underlying TTS service."""
        return self._service

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Set up the proxy and the current underlying TTS, if any."""
        await super().setup(setup)
        self._processor_setup = setup
        if self._service is not None:
            await self._service.setup(setup)

    async def cleanup(self) -> None:
        """Clean up the current underlying TTS, if any."""
        if self._service is not None:
            await self._service.cleanup()
        await super().cleanup()

    async def set_service(self, service: TTSService | None) -> None:
        """Replace the underlying TTS implementation, replaying StartFrame."""
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

    async def run_tts(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        text: str,
        context_id: str,
    ) -> AsyncGenerator[Frame, None]:
        """Stub — frames are routed through ``queue_frame`` on the underlying."""
        _ = text
        _ = context_id
        if False:
            yield Frame()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Forward frames to the current underlying TTS when configured."""
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self._start_frame = frame
        if self._service is not None:
            await self._service.queue_frame(frame, direction)
        elif isinstance(frame, SystemFrame):
            await self.push_frame(frame, direction)


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

    def __init__(
        self,
        client: UboRPCClient,
        config: TTSServiceConfig,
        *,
        google_credentials: str | None,
        selector: str,
    ) -> None:
        """Initialize TTS service with Google, OpenAI, ElevenLabs, Piper, and Rime."""
        self._config = config
        self._config.google_credentials = google_credentials

        # Cloud TTS providers go behind GenericTTSProxy so they always
        # live in Pipecat's switcher init list. The underlying real
        # Pipecat service is created/refreshed on demand in
        # ``_refresh_api_key_service`` whenever the user switches to
        # that provider — see ``_API_KEY_PROVIDERS`` below. Google is a
        # proxy too so a runtime voice change can rebuild it (Pipecat
        # freezes the switcher's service list at construction).
        self.google_tts = GenericTTSProxy()
        self.openai_tts = GenericTTSProxy()
        self.elevenlabs_tts = GenericTTSProxy()
        self.rime_tts = GenericTTSProxy()
        self.venice_tts = GenericTTSProxy()

        # Initialize Piper TTS. The model loads lazily: PiperTTSService
        # constructs even when no voice is on disk yet (first-time setup), so
        # this slot is never None and Piper always stays a selectable target in
        # the switcher's frozen init list. The store autorun registered in
        # `_ensure_autoruns_started` reconciles it to the user's persisted
        # voice (firing once on subscription, then on every change), and
        # `PiperTTSService.run_tts` loads the requested voice before the first
        # utterance — so a freshly-downloaded voice works without a restart.
        self.piper_tts = self._initialize_service(
            'Piper',
            lambda: PiperTTSService(voice_id=DEFAULT_PIPER_VOICE_ID)
            if PiperTTSService
            else None,
        )

        # Initialize Kokoro TTS only when the bundled model + voices
        # files are already on disk. If the user hasn't downloaded
        # Kokoro yet this stays None — picking Kokoro in the TTS
        # selector before downloading would simply have no active
        # service, and the subprocess is re-spawned the next time the
        # files exist so a download triggered from the Manage menu
        # picks up automatically.
        self.kokoro_tts = self._initialize_service(
            'Kokoro',
            lambda: KokoroTTSService(voice_id=DEFAULT_KOKORO_VOICE_ID)
            if KOKORO_MODEL_PATH.exists() and KOKORO_VOICES_PATH.exists()
            else None,
        )

        self._services = {
            'google': self.google_tts,
            'openai': self.openai_tts,
            'elevenlabs': self.elevenlabs_tts,
            'piper': self.piper_tts,
            'kokoro': self.kokoro_tts,
            'rime': self.rime_tts,
            'venice': self.venice_tts,
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

    # Cloud TTS providers refreshed lazily from secrets on selection. Same
    # shape as the LLM/STT counterpart: (env var holding the secret id,
    # config attr storing the value, factory method, proxy attribute).
    _API_KEY_PROVIDERS: dict[str, tuple[str, str, str, str]] = {  # noqa: RUF012
        'google': (
            'GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID',
            'google_credentials',
            '_create_google_service',
            'google_tts',
        ),
        'openai': (
            'OPENAI_API_KEY_SECRET_ID',
            'openai_api_key',
            '_create_openai_service',
            'openai_tts',
        ),
        'elevenlabs': (
            'ELEVENLABS_API_KEY_SECRET_ID',
            'elevenlabs_api_key',
            '_create_elevenlabs_service',
            'elevenlabs_tts',
        ),
        'rime': (
            'RIME_API_KEY_SECRET_ID',
            'rime_api_key',
            '_create_rime_service',
            'rime_tts',
        ),
        'venice': (
            'VENICE_API_KEY_SECRET_ID',
            'venice_api_key',
            '_create_venice_service',
            'venice_tts',
        ),
    }

    async def _refresh_api_key_service(self, id: str) -> None:
        """Re-query the API key for *id* and (re)build its underlying service.

        ElevenLabs is a special case — it needs the voice id alongside the
        api key. We refresh both here so the user only has to re-select the
        provider after editing either secret.
        """
        env_var, config_attr, factory_name, proxy_attr = self._API_KEY_PROVIDERS[id]
        api_key = await self.client.query_secret(os.environ[env_var])
        setattr(self._config, config_attr, api_key)

        if id == 'elevenlabs':
            self._config.elevenlabs_voice_id = await self.client.query_secret(
                os.environ['ELEVENLABS_VOICE_ID'],
            )

        factory = getattr(self, factory_name)
        real_service: TTSService | None = factory()

        proxy: GenericTTSProxy = getattr(self, proxy_attr)
        if proxy.service is real_service:
            return
        await proxy.set_service(real_service)

        logger.info(
            '{extra} TTS service refreshed',
            extra={
                'service_id': id,
                'has_api_key': bool(api_key),
                'has_service': real_service is not None,
            },
        )

    async def set_selected_service(self, id: str) -> None:
        """Set the selected TTS service, refreshing the API key first."""
        if id in self._API_KEY_PROVIDERS:
            await self._refresh_api_key_service(id)
        await super().set_selected_service(id)

    def _voice_for(self, service_id: str) -> str:
        """Return the user's selected voice for *service_id* (or its default)."""
        return (
            self._config.selected_voices.get(service_id)
            or _DEFAULT_CLOUD_VOICE.get(service_id, '')
        )

    def _create_google_service(self) -> GoogleTTSService | None:
        """Create Google TTS service if credentials are provided."""
        if not self._config.google_credentials:
            return None
        try:
            return GoogleTTSService(
                credentials=self._config.google_credentials,
                **google_voice_kwargs(self._voice_for('google')),
            )
        except Exception:
            logger.exception('Error while initializing Google TTS')
            return None

    def _create_openai_service(self) -> OpenAITTSService | None:
        """Create OpenAI TTS service if API key is provided."""
        if not self._config.openai_api_key:
            return None
        voice = self._voice_for('openai')
        openai_kwargs: dict[str, Any] = {'voice': voice} if voice else {}
        try:
            return OpenAITTSService(
                api_key=self._config.openai_api_key,
                **openai_kwargs,
            )
        except Exception:
            logger.exception('Error while initializing OpenAI TTS')
            return None

    def _create_elevenlabs_service(self) -> ElevenLabsTTSService | None:
        """Create ElevenLabs TTS service if both api key and voice id are set."""
        voice_id = (
            self._config.selected_voices.get('elevenlabs')
            or self._config.elevenlabs_voice_id
        )
        if not (self._config.elevenlabs_api_key and voice_id):
            return None
        try:
            return ElevenLabsTTSService(
                api_key=self._config.elevenlabs_api_key,
                voice_id=voice_id,
                sample_rate=24000,
                model='eleven_turbo_v2_5',
                enable_logging=True,
            )
        except Exception:
            logger.exception('Error while initializing ElevenLabs TTS')
            return None

    def _create_rime_service(self) -> RimeTTSService | None:
        """Create Rime TTS service if API key is provided."""
        if not self._config.rime_api_key:
            return None
        rime_voice = self._voice_for('rime')
        try:
            return RimeTTSService(
                api_key=self._config.rime_api_key,
                voice_id=rime_voice,
                model='mistv2',
                params=RimeTTSService.InputParams(
                    language=rime_language(rime_voice),
                    speed_alpha=1.0,
                    reduce_latency=False,
                    pause_between_brackets=True,
                    phonemize_between_brackets=False,
                ),
            )
        except Exception:
            logger.exception('Error while initializing Rime TTS')
            return None

    def _create_venice_service(self) -> VeniceTTSService | None:
        """Create Venice TTS service if API key is provided."""
        if not self._config.venice_api_key:
            return None
        try:
            return VeniceTTSService(
                api_key=self._config.venice_api_key,
                base_url=VENICE_BASE_URL,
                model=DEFAULT_VENICE_TTS_MODEL,
                voice=self._config.selected_voices.get('venice')
                or DEFAULT_VENICE_TTS_VOICE,
            )
        except Exception:
            logger.exception('Error while initializing Venice TTS')
            return None

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

        # Kokoro keeps every voice in the bundled ``voices-v1.0.bin``
        # that's already loaded into memory by ``KokoroTTSService``, so
        # a voice switch is a pure settings update — no file work.
        @self.client.autorun(['state.assistant.selected_kokoro_voice'])
        def _handle_kokoro_voice_change(data: list[StringValue]) -> None:
            voice_id = data[0].value
            target = self.kokoro_tts
            if isinstance(target, KokoroTTSService):
                target.request_voice(voice_id)

        # Cloud voices live in a dict that can't cross a gRPC autorun
        # selector, so an event carries each change. The cold-start replay
        # (one event per persisted ``selected_voices`` entry) seeds the cache;
        # later events rebuild the active provider's service with the new
        # voice. Mirrors the LLM model-change path in ``ubo_llm``.
        self.client.subscribe_event(
            event_type=Event(
                assistant_voice_changed_event=AssistantVoiceChangedEvent(),
            ),
            callback=self._handle_voice_changed_event,
        )

    def _handle_voice_changed_event(self, event: Event) -> None:
        """Cache the user's new cloud voice and refresh the active provider."""
        payload = event.assistant_voice_changed_event
        if payload is None:
            return
        service_id = _SERVICE_ID_BY_TTS_NAME.get(payload.tts_name)
        if service_id is None:
            return

        previous = self._config.selected_voices.get(service_id)
        self._config.selected_voices[service_id] = payload.voice_id
        if previous == payload.voice_id:
            return

        if (
            self._current_service_id == service_id
            and service_id in self._API_KEY_PROVIDERS
        ):
            logger.info(
                'Selected voice changed for active provider; refreshing',
                extra={'service_id': service_id, 'voice_id': payload.voice_id},
            )
            cast('ServiceSwitcher', self).create_task(
                self._refresh_api_key_service(service_id),
            )

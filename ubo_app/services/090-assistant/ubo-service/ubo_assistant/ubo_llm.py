"""LLM service that wraps multiple LLM services allowing switching between them."""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InputImageRawFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputImageRawFrame,
    StartFrame,
    SystemFrame,
    UserImageRequestFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.cerebras.llm import CerebrasLLMService
from pipecat.services.deepseek.llm import DeepSeekLLMService
from pipecat.services.google.vertex.llm import GoogleVertexLLMService
from pipecat.services.llm_service import (
    FunctionCallHandler,
    FunctionCallParams,
    LLMService,
)
from pipecat.services.mistral.llm import MistralLLMService
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openrouter.llm import OpenRouterLLMService
from pipecat.services.qwen.llm import QwenLLMService
from pipecat.services.xai.llm import GrokLLMService
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistanceTextFrame,
    AssistantGenericLlmProviderChangedEvent,
    AssistantLlmName,
    AssistantModelChangedEvent,
    AssistantOllamaThinkingChangedEvent,
    AssistantPipelineStage,
    Event,
    LocalizationRefreshWeatherAction,
    LocalizationSetLocationAction,
    LocationInfo,
    LocationSource,
    SpeechRecognitionRunCommandAction,
)

from ubo_assistant.constants import IS_RPI
from ubo_assistant.image_frame import ImageGenFrame
from ubo_assistant.switch import UboLLMSwitchService, make_empty_llm_settings

if TYPE_CHECKING:
    from pipecat.pipeline.service_switcher import ServiceSwitcher
    from ubo_bindings.ubo.v1 import WeatherCondition

    from ubo_assistant.system_prompt_watcher import SystemPromptWatcher

# How long ``get_weather`` waits for a core-side refetch to land in the autorun
# cache before answering with (and disclaiming) the last known conditions.
WEATHER_REFRESH_TIMEOUT_SECONDS = 4.0
WEATHER_REFRESH_POLL_SECONDS = 0.25

DEFAULT_GENERIC_LLM_MODEL = os.environ.get('DEFAULT_LLM_GENERIC_MODEL', 'gpt-4.1')
DEFAULT_OPENAI_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OPENAI_MODEL',
    'gpt-4o-mini',
)
DEFAULT_GROK_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_GROK_MODEL',
    'grok-4-0709',
)
DEFAULT_CEREBRAS_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_CEREBRAS_MODEL',
    'qwen-3-235b-a22b-instruct-2507',
)
DEFAULT_ANTHROPIC_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_ANTHROPIC_MODEL',
    'claude-sonnet-4-5',
)
DEFAULT_QWEN_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_QWEN_MODEL',
    'qwen-plus',
)
DEFAULT_DEEPSEEK_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_DEEPSEEK_MODEL',
    'deepseek-chat',
)
DEFAULT_OPENROUTER_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OPENROUTER_MODEL',
    'openai/gpt-4o-mini',
)
DEFAULT_MISTRAL_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_MISTRAL_MODEL',
    'mistral-small-latest',
)
DEFAULT_VENICE_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_MODEL',
    'llama-3.3-70b',
)
VENICE_BASE_URL = 'https://api.venice.ai/api/v1'
DEFAULT_OLLAMA_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OLLAMA_MODEL',
    'gemma3:1b' if IS_RPI else 'gemma3:27b-it-qat',
)

_DEFAULT_MODELS: dict[str, str] = {
    'openai': DEFAULT_OPENAI_MODEL,
    'grok': DEFAULT_GROK_MODEL,
    'cerebras': DEFAULT_CEREBRAS_MODEL,
    'anthropic': DEFAULT_ANTHROPIC_MODEL,
    'qwen': DEFAULT_QWEN_MODEL,
    'deepseek': DEFAULT_DEEPSEEK_MODEL,
    'openrouter': DEFAULT_OPENROUTER_MODEL,
    'mistral': DEFAULT_MISTRAL_MODEL,
    'venice': DEFAULT_VENICE_MODEL,
    'ollama': DEFAULT_OLLAMA_MODEL,
}


@dataclass
class LLMServiceConfig:
    """Configuration for LLM services."""

    google_credentials: str | None = None
    openai_api_key: str | None = None
    grok_api_key: str | None = None
    cerebras_api_key: str | None = None
    anthropic_api_key: str | None = None
    qwen_api_key: str | None = None
    deepseek_api_key: str | None = None
    openrouter_api_key: str | None = None
    mistral_api_key: str | None = None
    venice_api_key: str | None = None
    ollama_onprem_url: str | None = None
    generic_llm_base_url: str | None = None
    generic_llm_api_key: str | None = None
    generic_llm_model: str | None = None
    # User-selected model per provider, keyed by Ubo service id
    # (e.g. ``'openai' -> 'gpt-4o-mini'``). Refreshed from the store via an
    # autorun in UboLLMService so that picking a new model takes effect on
    # the next service refresh without restarting the subprocess.
    selected_models: dict[str, str] = field(default_factory=dict)
    # Per-Ollama-model thinking flag. Populated by
    # ``_handle_ollama_thinking_changed_event``; used when (re)creating the
    # local Ollama service so the right ``think`` flag is passed to Pipecat.
    # Persistent across restarts but the subprocess starts empty and gets
    # re-populated by the first event after restart.
    ollama_thinking_enabled: dict[str, bool] = field(default_factory=dict)


class GenericLLMProxy(LLMService):
    """Stable switcher branch for a dynamically refreshed generic LLM."""

    def __init__(self) -> None:
        """Initialize the proxy."""
        super().__init__(settings=make_empty_llm_settings())
        self._service: LLMService[Any] | None = None
        self._processor_setup: FrameProcessorSetup | None = None
        self._start_frame: StartFrame | None = None
        self._registered_functions: list[
            tuple[str | None, FunctionCallHandler, bool | None, float | None]
        ] = []

    @property
    def service(self) -> LLMService[Any] | None:
        """Current underlying LLM service."""
        return self._service

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Set up the proxy and current underlying LLM."""
        await super().setup(setup)
        self._processor_setup = setup
        if self._service is not None:
            await self._service.setup(setup)

    async def cleanup(self) -> None:
        """Clean up the current underlying LLM."""
        if self._service is not None:
            await self._service.cleanup()
        await super().cleanup()

    def register_function(
        self,
        function_name: str | None,
        handler: FunctionCallHandler,
        *,
        cancel_on_interruption: bool | None = True,
        timeout_secs: float | None = None,
    ) -> None:
        """Register a function on the proxy and current underlying service."""
        super().register_function(
            function_name,
            handler,
            cancel_on_interruption=cancel_on_interruption,
            timeout_secs=timeout_secs,
        )
        self._registered_functions.append(
            (function_name, handler, cancel_on_interruption, timeout_secs),
        )
        if self._service is not None:
            self._service.register_function(
                function_name,
                handler,
                cancel_on_interruption=cancel_on_interruption,
                timeout_secs=timeout_secs,
            )

    async def set_service(self, service: LLMService[Any] | None) -> None:
        """Replace the underlying generic LLM implementation."""
        if self._service is not None:
            await self._service.cleanup()

        self._service = service
        if self._service is None:
            return

        self._service.push_frame = self.push_frame
        for (
            function_name,
            handler,
            cancel_on_interruption,
            timeout_secs,
        ) in self._registered_functions:
            self._service.register_function(
                function_name,
                handler,
                cancel_on_interruption=cancel_on_interruption,
                timeout_secs=timeout_secs,
            )
        if self._processor_setup is not None:
            await self._service.setup(self._processor_setup)
        if self._start_frame is not None:
            await self._service.queue_frame(self._start_frame)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Forward frames to the current underlying LLM when configured."""
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self._start_frame = frame
        if self._service is not None:
            await self._service.queue_frame(frame, direction)
        elif isinstance(frame, SystemFrame):
            await self.push_frame(frame, direction)


# Maps the proto enum (which only carries the upper-cased member name) to the
# string service id used as a key in ``self._services``. We can't derive this
# from ``.name.lower()`` because two StrEnum members on the parent side use
# values that don't match their lowercased name:
#   GOOGLE  -> 'google_vertex'   ('google' != value)
#   GENERIC -> 'generic_llm'     ('generic' != value)
# Mapping miss => the change event is silently ignored, which makes the
# user-visible "model picked for Google/Generic has no effect" bug loud and
# quick to spot if a new LLM is added without updating this dict.
_SERVICE_ID_BY_LLM_NAME: dict[AssistantLlmName, str] = {
    AssistantLlmName.OLLAMA: 'ollama',
    AssistantLlmName.OLLAMA_ONPREM: 'ollama_onprem',
    AssistantLlmName.GOOGLE: 'google_vertex',
    AssistantLlmName.OPENAI: 'openai',
    AssistantLlmName.GROK: 'grok',
    AssistantLlmName.CEREBRAS: 'cerebras',
    AssistantLlmName.ANTHROPIC: 'anthropic',
    AssistantLlmName.QWEN: 'qwen',
    AssistantLlmName.DEEPSEEK: 'deepseek',
    AssistantLlmName.OPENROUTER: 'openrouter',
    AssistantLlmName.MISTRAL: 'mistral',
    AssistantLlmName.VENICE: 'venice',
    AssistantLlmName.GENERIC: 'generic_llm',
}


class UboLLMService(UboLLMSwitchService):
    """LLM service that wraps multiple LLM services allowing switching between them."""

    def __init__(
        self,
        client: UboRPCClient,
        config: LLMServiceConfig,
        selector: str,
        # Quoted: this module has no ``from __future__ import annotations``, so
        # a bare TYPE_CHECKING-only name would be evaluated at class creation.
        system_prompt_watcher: 'SystemPromptWatcher | None' = None,
    ) -> None:
        """Initialize LLM service with various services including remote Ollama."""
        self._config = config
        # Id of the most recent LLMContextFrame routed to the active LLM.
        # The assistant aggregator sits outside the ParallelPipeline and pushes
        # its trigger context frame UPSTREAM into it; the nested parallel
        # pipelines + producer/consumer pair fan that single frame out so it
        # reaches the switcher twice, making the LLM describe a captured image
        # twice. Dropping a re-delivery of the same frame id collapses it back
        # to one inference.
        self._last_llm_context_frame_id: int | None = None
        # Id of the most recent input image mirrored to the output stream. The
        # captured frame can be delivered to this switcher more than once via
        # the same nested-ParallelPipeline fan-out, which would mirror it twice
        # and open the image_viewer twice (one render overriding the other).
        # Mirroring each unique frame once keeps a single image_viewer render.
        self._last_mirrored_image_frame_id: int | None = None

        # Initialize all services. Cloud providers that take a runtime API key
        # are wrapped in GenericLLMProxy so they always live in Pipecat's
        # ServiceSwitcher init list. The underlying real Pipecat service is
        # created/refreshed on demand in ``_refresh_api_key_service`` whenever
        # the user switches to that provider — see Phase 1.5 design notes for
        # why the proxy pattern is required (Pipecat 1.0 freezes its services
        # list at __init__).
        self.google_vertex_llm = self._create_google_vertex_service()
        self.openai_llm = GenericLLMProxy()
        self.grok_llm = GenericLLMProxy()
        self.cerebras_llm = GenericLLMProxy()
        self.anthropic_llm = GenericLLMProxy()
        self.qwen_llm = GenericLLMProxy()
        self.deepseek_llm = GenericLLMProxy()
        self.openrouter_llm = GenericLLMProxy()
        self.mistral_llm = GenericLLMProxy()
        self.venice_llm = GenericLLMProxy()
        # Local Ollama goes behind a GenericLLMProxy so we can hot-swap it when
        # the user picks a new curated model or toggles thinking mode.
        self.ollama_llm = GenericLLMProxy()
        self.ollama_onprem_llm = self._create_ollama_onprem_service()
        self.generic_llm = GenericLLMProxy()

        # Build services dictionary
        self._services = {
            'google_vertex': self.google_vertex_llm,
            'openai': self.openai_llm,
            'grok': self.grok_llm,
            'cerebras': self.cerebras_llm,
            'anthropic': self.anthropic_llm,
            'qwen': self.qwen_llm,
            'deepseek': self.deepseek_llm,
            'openrouter': self.openrouter_llm,
            'mistral': self.mistral_llm,
            'venice': self.venice_llm,
            'ollama': self.ollama_llm,
            'ollama_onprem': self.ollama_onprem_llm,
            'generic_llm': self.generic_llm,
        }

        # Initialize parent classes
        UboLLMSwitchService.__init__(
            self,
            client=client,
            selector=selector,
            settings=make_empty_llm_settings(),
            system_prompt_watcher=system_prompt_watcher,
        )

        # Register built-in functions
        self._register_builtin_functions()

    def _ensure_autoruns_started(self) -> None:
        """Start parent autoruns then subscribe to user-selected model changes."""
        if self._autoruns_started:
            return
        super()._ensure_autoruns_started()

        # Subscribe to AssistantModelChangedEvent for both:
        #   (a) the imperative "swap the active provider now" path on user
        #       change of model, and
        #   (b) the cold-start seed: the parent's gRPC ``_send_initial_state``
        #       replays one event per persisted ``selected_models`` entry as
        #       soon as we subscribe, so this handler populates
        #       ``self._config.selected_models`` with the on-disk values.
        self.client.subscribe_event(
            event_type=Event(
                assistant_model_changed_event=AssistantModelChangedEvent(),
            ),
            callback=self._handle_model_changed_event,
        )
        # The active named generic-LLM provider changed (or its credentials
        # were edited). The parent's ``selected_llm`` autorun won't refire
        # while its value stays ``generic_llm``, so this event is the only
        # signal — refresh unconditionally from the canonical secrets; the
        # rebuild is cheap and a refresh while generic isn't active is
        # harmless (the proxy only routes frames when selected).
        self.client.subscribe_event(
            event_type=Event(
                assistant_generic_llm_provider_changed_event=(
                    AssistantGenericLlmProviderChangedEvent()
                ),
            ),
            callback=self._handle_generic_llm_provider_changed_event,
        )
        # Same pattern for Ollama thinking toggle (covers both runtime toggles
        # and the cold-start replay of ``ollama_thinking_enabled``).
        self.client.subscribe_event(
            event_type=Event(
                assistant_ollama_thinking_changed_event=(
                    AssistantOllamaThinkingChangedEvent()
                ),
            ),
            callback=self._handle_ollama_thinking_changed_event,
        )

    def _handle_model_changed_event(self, event: Event) -> None:
        """Cache the user's new model and refresh the active provider."""
        payload = event.assistant_model_changed_event
        if payload is None:
            return
        service_id = _SERVICE_ID_BY_LLM_NAME.get(payload.llm_name)
        if service_id is None:
            return
        new_model = payload.model

        previous = self._config.selected_models.get(service_id)
        self._config.selected_models[service_id] = new_model

        current_id = self._current_service_id
        is_active = current_id == service_id and (
            current_id in self._API_KEY_PROVIDERS or current_id == 'ollama'
        )
        # Re-asserting the same model is normally a no-op, but for the active
        # local-Ollama provider it's also how a just-finished model download
        # signals readiness: the OLLamaLLMService built when Ollama was first
        # selected may have started against a not-yet-running daemon (the model
        # wasn't downloaded yet), so it must be rebuilt now that the model is
        # available — otherwise the assistant stays silent until a restart.
        # API-key providers have no such readiness handshake, so they keep the
        # dedup to avoid churning their service on redundant re-selections.
        if previous == new_model and not (is_active and current_id == 'ollama'):
            return

        if is_active and current_id is not None:
            logger.info(
                'Selected model changed for active provider; refreshing {extra}',
                extra={
                    'service_id': current_id,
                    'previous_model': previous,
                    'new_model': new_model,
                },
            )
            task_runner = cast('ServiceSwitcher', self).create_task
            if current_id == 'ollama':
                task_runner(self._refresh_ollama_service())
            else:
                task_runner(self._refresh_api_key_service(current_id))

    def _handle_generic_llm_provider_changed_event(self, event: Event) -> None:
        """Rebuild the generic LLM service from the canonical secrets."""
        payload = event.assistant_generic_llm_provider_changed_event
        if payload is None:
            return
        logger.info(
            'Active generic LLM provider changed; refreshing {extra}',
            extra={'provider_id': payload.provider_id},
        )
        cast('ServiceSwitcher', self).create_task(
            self._refresh_generic_llm_service(),
        )

    def _handle_ollama_thinking_changed_event(self, event: Event) -> None:
        """Cache thinking-toggle changes and refresh the Ollama service."""
        payload = event.assistant_ollama_thinking_changed_event
        if payload is None:
            return
        self._config.ollama_thinking_enabled[payload.model] = payload.enabled

        if self._current_service_id != 'ollama':
            return
        if self._config.selected_models.get('ollama') != payload.model:
            # Toggle applied to a non-active model; nothing to refresh now.
            return
        logger.info(
            'Ollama thinking toggled; refreshing service {extra}',
            extra={'model': payload.model, 'enabled': payload.enabled},
        )
        cast('ServiceSwitcher', self).create_task(self._refresh_ollama_service())

    # Cloud LLM providers whose only runtime input is a single API key. Each
    # entry maps a service id to (env var holding the secret id, config attr
    # storing the value, factory method building the real Pipecat service,
    # proxy attribute on this instance). The proxies are stable members of
    # Pipecat's switcher init list; the underlying real services get
    # created/swapped here when the user picks the provider.
    _API_KEY_PROVIDERS: dict[str, tuple[str, str, str, str]] = {  # noqa: RUF012
        'openai': (
            'OPENAI_API_KEY_SECRET_ID',
            'openai_api_key',
            '_create_openai_service',
            'openai_llm',
        ),
        'grok': (
            'GROK_API_KEY_SECRET_ID',
            'grok_api_key',
            '_create_grok_service',
            'grok_llm',
        ),
        'cerebras': (
            'CEREBRAS_API_KEY_SECRET_ID',
            'cerebras_api_key',
            '_create_cerebras_service',
            'cerebras_llm',
        ),
        'anthropic': (
            'ANTHROPIC_API_KEY_SECRET_ID',
            'anthropic_api_key',
            '_create_anthropic_service',
            'anthropic_llm',
        ),
        'qwen': (
            'QWEN_API_KEY_SECRET_ID',
            'qwen_api_key',
            '_create_qwen_service',
            'qwen_llm',
        ),
        'deepseek': (
            'DEEPSEEK_API_KEY_SECRET_ID',
            'deepseek_api_key',
            '_create_deepseek_service',
            'deepseek_llm',
        ),
        'openrouter': (
            'OPENROUTER_API_KEY_SECRET_ID',
            'openrouter_api_key',
            '_create_openrouter_service',
            'openrouter_llm',
        ),
        'mistral': (
            'MISTRAL_API_KEY_SECRET_ID',
            'mistral_api_key',
            '_create_mistral_service',
            'mistral_llm',
        ),
        'venice': (
            'VENICE_API_KEY_SECRET_ID',
            'venice_api_key',
            '_create_venice_service',
            'venice_llm',
        ),
    }

    async def _refresh_api_key_service(self, id: str) -> None:
        """Re-query the API key for *id* and (re)build its underlying service."""
        env_var, config_attr, factory_name, proxy_attr = self._API_KEY_PROVIDERS[id]
        api_key = await self.client.query_secret(os.environ[env_var])
        setattr(self._config, config_attr, api_key)

        factory = getattr(self, factory_name)
        real_service: LLMService[Any] | None = factory()

        proxy: GenericLLMProxy = getattr(self, proxy_attr)
        if proxy.service is real_service:
            return
        await proxy.set_service(real_service)

        logger.info(
            '{extra} service refreshed',
            extra={
                'service_id': id,
                'has_api_key': bool(api_key),
                'has_service': real_service is not None,
            },
        )

    async def _refresh_generic_llm_service(self) -> None:
        """Refresh Generic LLM config from secrets before selecting it."""
        generic_llm_base_url = await self.client.query_secret(
            os.environ['GENERIC_LLM_BASE_URL_SECRET_ID'],
        )
        generic_llm_api_key = await self.client.query_secret(
            os.environ['GENERIC_LLM_API_KEY_SECRET_ID'],
        )
        generic_llm_model = await self.client.query_secret(
            os.environ['GENERIC_LLM_MODEL_SECRET_ID'],
        )

        self._config.generic_llm_base_url = generic_llm_base_url
        self._config.generic_llm_api_key = generic_llm_api_key
        self._config.generic_llm_model = generic_llm_model

        generic_llm = self._create_generic_llm_service()

        if generic_llm is None:
            logger.warning('Generic LLM is not configured')
            await self.generic_llm.set_service(None)
            return

        await self.generic_llm.set_service(generic_llm)
        logger.info(
            'Generic LLM service refreshed {extra}',
            extra={
                'base_url': generic_llm_base_url,
                'model': generic_llm_model or DEFAULT_GENERIC_LLM_MODEL,
                'has_api_key': bool(generic_llm_api_key),
            },
        )

    async def set_selected_service(self, id: str) -> None:
        """Set the selected service, refreshing dynamic-config providers first."""
        if id == 'generic_llm':
            await self._refresh_generic_llm_service()
        elif id == 'ollama':
            await self._refresh_ollama_service()
        elif id in self._API_KEY_PROVIDERS:
            await self._refresh_api_key_service(id)
        await super().set_selected_service(id)

    def _create_google_vertex_service(self) -> GoogleVertexLLMService | None:
        """Create Google Vertex LLM service if credentials are provided."""
        if not self._config.google_credentials:
            return None

        try:
            project_id = json.loads(self._config.google_credentials).get('project_id')
            return GoogleVertexLLMService(
                credentials=self._config.google_credentials,
                project_id=project_id,
            )
        except Exception as exception:
            logger.exception(
                'Error while initializing Google Vertex LLM {extra}',
                extra={'exception': exception},
            )
            return None

    def _resolve_model(self, service_id: str) -> str:
        """Return the model the user has selected for *service_id*.

        Falls back to ``_DEFAULT_MODELS[service_id]`` when ``selected_models``
        has no entry yet (e.g. before the autorun has fired or when the user
        has never picked a model for the provider).
        """
        return (
            self._config.selected_models.get(service_id) or _DEFAULT_MODELS[service_id]
        )

    def _create_openai_service(self) -> OpenAILLMService | None:
        """Create OpenAI LLM service if API key is provided."""
        if not self._config.openai_api_key:
            return None

        try:
            return OpenAILLMService(
                api_key=self._config.openai_api_key,
                settings=OpenAILLMService.Settings(model=self._resolve_model('openai')),
            )
        except Exception:
            logger.exception('Error while initializing OpenAI LLM')
            return None

    def _create_grok_service(self) -> GrokLLMService | None:
        """Create Grok LLM service if API key is provided."""
        if not self._config.grok_api_key:
            return None

        try:
            return GrokLLMService(
                api_key=self._config.grok_api_key,
                settings=GrokLLMService.Settings(model=self._resolve_model('grok')),
            )
        except Exception:
            logger.exception('Error while initializing Grok LLM')
            return None

    def _create_cerebras_service(self) -> CerebrasLLMService | None:
        """Create Cerebras LLM service if API key is provided."""
        if not self._config.cerebras_api_key:
            return None

        try:
            return CerebrasLLMService(
                api_key=self._config.cerebras_api_key,
                settings=CerebrasLLMService.Settings(
                    model=self._resolve_model('cerebras'),
                    temperature=0.7,
                    max_completion_tokens=1000,
                ),
            )
        except Exception:
            logger.exception('Error while initializing Cerebras LLM')
            return None

    def _create_anthropic_service(self) -> AnthropicLLMService | None:
        """Create Anthropic LLM service if API key is provided."""
        if not self._config.anthropic_api_key:
            return None

        try:
            return AnthropicLLMService(
                api_key=self._config.anthropic_api_key,
                settings=AnthropicLLMService.Settings(
                    model=self._resolve_model('anthropic'),
                ),
            )
        except Exception:
            logger.exception('Error while initializing Anthropic LLM')
            return None

    def _create_qwen_service(self) -> QwenLLMService | None:
        """Create Qwen LLM service if API key is provided."""
        if not self._config.qwen_api_key:
            return None

        try:
            return QwenLLMService(
                api_key=self._config.qwen_api_key,
                settings=QwenLLMService.Settings(model=self._resolve_model('qwen')),
            )
        except Exception:
            logger.exception('Error while initializing Qwen LLM')
            return None

    def _create_deepseek_service(self) -> DeepSeekLLMService | None:
        """Create DeepSeek LLM service if API key is provided."""
        if not self._config.deepseek_api_key:
            return None

        try:
            return DeepSeekLLMService(
                api_key=self._config.deepseek_api_key,
                settings=DeepSeekLLMService.Settings(
                    model=self._resolve_model('deepseek'),
                ),
            )
        except Exception:
            logger.exception('Error while initializing DeepSeek LLM')
            return None

    def _create_openrouter_service(self) -> OpenRouterLLMService | None:
        """Create OpenRouter LLM service if API key is provided."""
        if not self._config.openrouter_api_key:
            return None

        try:
            return OpenRouterLLMService(
                api_key=self._config.openrouter_api_key,
                settings=OpenRouterLLMService.Settings(
                    model=self._resolve_model('openrouter'),
                ),
            )
        except Exception:
            logger.exception('Error while initializing OpenRouter LLM')
            return None

    def _create_mistral_service(self) -> MistralLLMService | None:
        """Create Mistral LLM service if API key is provided."""
        if not self._config.mistral_api_key:
            return None

        try:
            return MistralLLMService(
                api_key=self._config.mistral_api_key,
                settings=MistralLLMService.Settings(
                    model=self._resolve_model('mistral'),
                ),
            )
        except Exception:
            logger.exception('Error while initializing Mistral LLM')
            return None

    def _create_venice_service(self) -> OpenAILLMService | None:
        """Create Venice LLM service via the OpenAI-compatible Venice endpoint."""
        if not self._config.venice_api_key:
            return None

        try:
            return OpenAILLMService(
                api_key=self._config.venice_api_key,
                base_url=VENICE_BASE_URL,
                settings=OpenAILLMService.Settings(
                    model=self._resolve_model('venice'),
                ),
            )
        except Exception:
            logger.exception('Error while initializing Venice LLM')
            return None

    def _create_ollama_service(self) -> OLLamaLLMService | None:
        """Create the local Ollama LLM service using the current selection.

        Reads the user-selected model from ``selected_models['ollama']`` and
        the per-model thinking flag from ``ollama_thinking_enabled``. Pipecat
        hits Ollama's OpenAI-compatible endpoint (``/v1``), so we control
        thinking via ``reasoning_effort`` rather than the native ``think``
        boolean — the latter is silently ignored on the OpenAI-compatible
        endpoint. We send ``reasoning_effort`` in both states so toggling
        "off" actually disables thinking (the default for qwen3 etc. is on).
        """
        try:
            model = self._resolve_model('ollama')
            think = self._config.ollama_thinking_enabled.get(model, False)
            return OLLamaLLMService(
                settings=OLLamaLLMService.Settings(
                    model=model,
                    extra={'reasoning_effort': 'high' if think else 'none'},
                ),
            )
        except Exception:
            logger.exception('Error while initializing Ollama LLM')
            return None

    async def _refresh_ollama_service(self) -> None:
        """Re-create the local Ollama service after a model or thinking change."""
        real_service = self._create_ollama_service()
        proxy: GenericLLMProxy = self.ollama_llm
        if proxy.service is real_service:
            return
        await proxy.set_service(real_service)
        logger.info(
            'Ollama service refreshed {extra}',
            extra={
                'model': self._resolve_model('ollama'),
                'has_service': real_service is not None,
            },
        )

    def _create_ollama_onprem_service(self) -> OLLamaLLMService | None:
        """Create remote Ollama LLM service if URL is provided."""
        if not self._config.ollama_onprem_url:
            return None

        try:
            # Ollama's OpenAI-compatible API is at /v1 endpoint
            base_url = self._config.ollama_onprem_url.rstrip('/') + '/v1'
            return OLLamaLLMService(
                base_url=base_url,
                settings=OLLamaLLMService.Settings(model='granite3.3:8b'),
            )
        except Exception:
            logger.exception(
                'Error while initializing remote Ollama LLM {extra}',
                extra={'url': self._config.ollama_onprem_url},
            )
            return None

    def _create_generic_llm_service(self) -> OpenAILLMService | None:
        """Create a generic OpenAI-compatible LLM service if configured."""
        if not self._config.generic_llm_base_url:
            return None

        try:
            return OpenAILLMService(
                api_key=self._config.generic_llm_api_key or 'not-needed',
                base_url=self._config.generic_llm_base_url.rstrip('/'),
                settings=OpenAILLMService.Settings(
                    model=self._config.generic_llm_model or DEFAULT_GENERIC_LLM_MODEL,
                ),
            )
        except Exception:
            logger.exception(
                'Error while initializing Generic LLM {extra}',
                extra={'url': self._config.generic_llm_base_url},
            )
            return None

    def _register_builtin_functions(self) -> None:
        """Register built-in functions with all services."""
        for service in self.service_map.values():
            service.register_function('draw_image', self.draw_image)
            service.register_function('get_image', self.get_image)
            service.register_function('run_device_command', self.run_device_command)
            service.register_function('get_current_time', self.get_current_time)
            service.register_function('get_weather', self.get_weather)
            service.register_function('set_location', self.set_location)

    def register_function(
        self,
        function_name: str | None,
        handler: FunctionCallHandler,
        *,
        cancel_on_interruption: bool | None = True,
        timeout_secs: float | None = None,
    ) -> None:
        """Register a function with all underlying LLM services.

        This method is called by MCP clients to register external tools.
        """
        for service in self.service_map.values():
            if service is None:
                continue
            service.register_function(
                function_name,
                handler,
                cancel_on_interruption=cancel_on_interruption,
                timeout_secs=timeout_secs,
            )

    async def draw_image(self, params: FunctionCallParams) -> None:
        """Generate an image based on a text prompt."""
        prompt = params.arguments['prompt']
        await self.push_frame(ImageGenFrame(text=prompt))
        await params.result_callback(
            f'Image generator here, going for {prompt}.',
        )

    async def run_device_command(self, params: FunctionCallParams) -> None:
        """Run one of the user's configured voice shortcuts (stage 2).

        Stage 1 matches shortcut phrases locally against the Vosk grammar and
        never reaches the LLM. This is the fallback for a near-miss phrasing that
        did.

        The dispatch is optimistic: there is no ack channel back from the store,
        so the result is reported as soon as the action is on the wire. The core
        validates the id again anyway (an unknown one is a no-op there).
        """
        command_id = params.arguments['command_id']
        command = next(
            (
                candidate
                for candidate in self._device_commands
                if candidate.id == command_id
            ),
            None,
        )
        if command is None:
            logger.warning(
                'LLM asked for an unknown device command {extra}',
                extra={'command_id': command_id},
            )
            await params.result_callback(
                f'There is no device command with the id {command_id!r}.',
            )
            return

        logger.info(
            'Running device command on behalf of the LLM {extra}',
            extra={'command_id': command_id, 'label': command.label},
        )
        self.client.dispatch(
            action=Action(
                speech_recognition_run_command_action=(
                    SpeechRecognitionRunCommandAction(command_id=command_id)
                ),
            ),
        )
        await params.result_callback(
            f'Running the "{command.label}" command now.',
        )

    async def get_current_time(self, params: FunctionCallParams) -> None:
        """Tell the LLM the current local time at the device's location.

        The model has no clock, so this is the only way it can answer a time or
        date question correctly. Falls back to the system timezone (and says so)
        when the device's location isn't known yet.
        """
        timezone = self._location.timezone if self._location else None
        if timezone:
            try:
                now = datetime.now(ZoneInfo(timezone))
            except (ZoneInfoNotFoundError, ValueError):
                logger.warning(
                    'Unknown timezone in localization state {extra}',
                    extra={'timezone': timezone},
                )
                now = datetime.now().astimezone()
                timezone = None
        else:
            now = datetime.now().astimezone()

        stamp = now.strftime('%I:%M %p on %A, %B %d, %Y').replace(' 0', ' ')
        if timezone:
            await params.result_callback(f'It is {stamp} ({timezone}).')
            return
        await params.result_callback(
            f'It is {stamp}. Note: the device location is unknown, so this is '
            "the system clock's timezone and may be wrong. Consider asking the "
            'user where they are and calling set_location.',
        )

    async def get_weather(self, params: FunctionCallParams) -> None:
        """Tell the LLM the current weather at the device's location.

        There is no one-shot store read over gRPC, so a stale cache is refreshed
        by dispatching a refresh action to the core and waiting for the autorun
        to deliver the new value. If it doesn't arrive in time we answer with the
        last known conditions rather than nothing, and say how old they are.
        """
        if self._location is None:
            await params.result_callback(
                "The device's location is not known yet, so the weather cannot "
                'be looked up. Ask the user where they are and call set_location.',
            )
            return

        weather = self._weather
        if weather is None or (weather.expires_at or 0) <= time.time():
            weather = await self._refresh_weather(previous=weather)

        if weather is None:
            await params.result_callback(
                'The weather service could not be reached just now.',
            )
            return

        place = self._location.city or 'the device location'
        temperature_unit = weather.temperature_display_unit or '°C'
        temperature_unit_name = temperature_unit.lstrip('°') or 'C'
        parts = [
            f'{weather.temperature_display_value:.0f} degrees {temperature_unit_name}',
            f'conditions "{weather.symbol_code}"',
        ]
        if weather.wind_speed_display_value is not None:
            parts.append(
                f'wind {weather.wind_speed_display_value:.0f} '
                f'{weather.wind_speed_display_unit}',
            )

        summary = f'Current weather in {place}: {", ".join(parts)}.'
        if (weather.expires_at or 0) <= time.time():
            age_minutes = int((time.time() - (weather.fetched_at or 0)) / 60)
            summary += (
                f' (This reading is about {age_minutes} minutes old — the '
                'weather service is not responding right now.)'
            )
        await params.result_callback(summary)

    async def _refresh_weather(
        self,
        *,
        previous: 'WeatherCondition | None',
    ) -> 'WeatherCondition | None':
        """Ask the core to refetch the weather, then wait for the autorun to land."""
        self.client.dispatch(
            action=Action(
                localization_refresh_weather_action=(
                    LocalizationRefreshWeatherAction()
                ),
            ),
        )

        previous_stamp = previous.fetched_at if previous else None
        deadline = time.time() + WEATHER_REFRESH_TIMEOUT_SECONDS
        while time.time() < deadline:
            await asyncio.sleep(WEATHER_REFRESH_POLL_SECONDS)
            current = self._weather
            if current is not None and current.fetched_at != previous_stamp:
                return current

        logger.warning('Weather refresh timed out; answering from cache')
        return previous

    async def set_location(self, params: FunctionCallParams) -> None:
        """Set the device's location from what the user said in conversation.

        The model supplies the coordinates and IANA timezone it knows for the
        named city, so no geocoding service is needed. Dispatch is optimistic,
        like ``run_device_command`` — there is no ack channel back from the store.
        """

        def _text(key: str) -> str | None:
            value = params.arguments.get(key)
            return value.strip() or None if isinstance(value, str) else None

        city = _text('city')
        country = _text('country')
        country_code = _text('country_code')
        timezone = _text('timezone')

        try:
            latitude = float(params.arguments['latitude'])
            longitude = float(params.arguments['longitude'])
        except (KeyError, TypeError, ValueError):
            await params.result_callback(
                'Latitude and longitude must both be numbers.',
            )
            return

        if timezone is None:
            await params.result_callback(
                'An IANA timezone name is required, for example "Europe/Lisbon".',
            )
            return

        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            await params.result_callback(
                f'{timezone!r} is not a valid IANA timezone name. Use one like '
                '"Europe/Lisbon".',
            )
            return

        logger.info(
            'Setting device location on behalf of the LLM {extra}',
            extra={'city': city, 'country': country, 'timezone': timezone},
        )
        self.client.dispatch(
            action=Action(
                localization_set_location_action=LocalizationSetLocationAction(
                    location=LocationInfo(
                        latitude=latitude,
                        longitude=longitude,
                        city=city,
                        country=country,
                        country_code=country_code,
                        timezone=timezone,
                    ),
                    source=LocationSource.MANUAL,
                ),
            ),
        )
        where = ', '.join(part for part in (city, country) if part) or 'that location'
        await params.result_callback(f'Location set to {where}.')

    async def get_image(self, params: FunctionCallParams) -> None:
        """Get an image from the video stream based on a question."""
        prompt = params.arguments['prompt']
        source = params.arguments['source']
        # Link the image request back to this function call (tool_call_id +
        # result_callback). The context aggregator then routes the returned
        # image through the function-result path, which appends it and runs
        # inference exactly once. A bare request (no linkage) instead appends
        # the image *and* leaves the call dangling, making the assistant
        # describe the picture twice.
        await params.llm.push_frame(
            UserImageRequestFrame(
                user_id='-',
                text=prompt,
                video_source=source,
                append_to_context=True,
                function_name=params.function_name,
                tool_call_id=params.tool_call_id,
                result_callback=params.result_callback,
            ),
            FrameDirection.UPSTREAM,
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Mirror input images in output stream."""
        # Drop a duplicate delivery of the same context frame so the active LLM
        # only runs once per trigger. The frame fans out through the nested
        # ParallelPipelines (see ``_last_llm_context_frame_id``) and would
        # otherwise reach the switcher — and the LLM — twice. Not routing it
        # (skipping ``super().process_frame``) is the drop; a genuine new
        # trigger always carries a fresh frame id.
        if isinstance(frame, LLMContextFrame):
            if frame.id == self._last_llm_context_frame_id:
                logger.warning(
                    'Dropping duplicate LLMContextFrame delivery {extra}',
                    extra={'frame_id': frame.id, 'frame_name': frame.name},
                )
                return
            self._last_llm_context_frame_id = frame.id

        await super().process_frame(frame, direction)

        if (
            isinstance(frame, InputImageRawFrame)
            and frame.id != self._last_mirrored_image_frame_id
        ):
            self._last_mirrored_image_frame_id = frame.id
            output_frame = OutputImageRawFrame(
                image=frame.image,
                size=frame.size,
                format=frame.format,
            )
            await self.push_frame(output_frame)

    async def push_frame(
        self,
        frame: Frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> None:
        """Dispatch the frame in ubo-app's redux bus if it's audio, image or text."""
        if isinstance(frame, LLMFullResponseStartFrame):
            self._reset_assistance()

        if isinstance(frame, LLMTextFrame):
            self._report_assistance_frame(
                AcceptableAssistanceFrame(
                    assistance_text_frame=AssistanceTextFrame(
                        text=frame.text,
                        timestamp=self.client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._assistance_index,
                        source=AssistantPipelineStage.LLM,
                    ),
                ),
            )
        elif isinstance(frame, LLMFullResponseEndFrame):
            # End-of-response marker so streaming consumers know the assistant
            # reply is complete (mirrors GRPCTerminalCollector.dispatch_last_frame).
            self._report_assistance_frame(
                AcceptableAssistanceFrame(
                    assistance_text_frame=AssistanceTextFrame(
                        text='',
                        timestamp=self.client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._assistance_index,
                        source=AssistantPipelineStage.LLM,
                        is_last_frame=True,
                    ),
                ),
            )

        await super().push_frame(frame, direction)

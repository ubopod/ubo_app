"""LLM service that wraps multiple LLM services allowing switching between them."""

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InputImageRawFrame,
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
    AssistanceTextFrame,
    AssistantLlmName,
    AssistantModelChangedEvent,
    AssistantOllamaThinkingChangedEvent,
    Event,
)

from ubo_assistant.constants import IS_RPI
from ubo_assistant.image_frame import ImageGenFrame
from ubo_assistant.switch import UboLLMSwitchService, make_empty_llm_settings

if TYPE_CHECKING:
    from pipecat.pipeline.service_switcher import ServiceSwitcher

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
        self._service: LLMService | None = None
        self._processor_setup: FrameProcessorSetup | None = None
        self._start_frame: StartFrame | None = None
        self._registered_functions: list[
            tuple[str | None, FunctionCallHandler, bool, float | None]
        ] = []

    @property
    def service(self) -> LLMService | None:
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
        cancel_on_interruption: bool = True,
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

    async def set_service(self, service: LLMService | None) -> None:
        """Replace the underlying generic LLM implementation."""
        if self._service is not None:
            await self._service.cleanup()

        self._service = service
        if self._service is None:
            return

        self._service.push_frame = self.push_frame
        for function_name, handler, cancel_on_interruption, timeout_secs in (
            self._registered_functions
        ):
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


class UboLLMService(UboLLMSwitchService):
    """LLM service that wraps multiple LLM services allowing switching between them."""

    def __init__(
        self,
        client: UboRPCClient,
        config: LLMServiceConfig,
        selector: str,
    ) -> None:
        """Initialize LLM service with various services including remote Ollama."""
        self._config = config

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
        # The pipecat-side Event wrappers come through as betterproto enums
        # whose ``.name`` is upper-cased; map back to the lowercase service id.
        llm_enum: AssistantLlmName = payload.llm_name
        if llm_enum.name is None:
            return
        service_id = llm_enum.name.lower()
        new_model = payload.model

        previous = self._config.selected_models.get(service_id)
        self._config.selected_models[service_id] = new_model
        if previous == new_model:
            return

        current_id = self._current_service_id
        if current_id == service_id and (
            current_id in self._API_KEY_PROVIDERS or current_id == 'ollama'
        ):
            logger.info(
                'Selected model changed for active provider; refreshing',
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
            'Ollama thinking toggled; refreshing service',
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
    }

    async def _refresh_api_key_service(self, id: str) -> None:
        """Re-query the API key for *id* and (re)build its underlying service."""
        env_var, config_attr, factory_name, proxy_attr = self._API_KEY_PROVIDERS[id]
        api_key = await self.client.query_secret(os.environ[env_var])
        setattr(self._config, config_attr, api_key)

        factory = getattr(self, factory_name)
        real_service: LLMService | None = factory()

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
                'Error while initializing Google Vertex LLM',
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
            self._config.selected_models.get(service_id)
            or _DEFAULT_MODELS[service_id]
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
            'Ollama service refreshed',
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
                'Error while initializing remote Ollama LLM',
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
                    model=self._config.generic_llm_model
                    or DEFAULT_GENERIC_LLM_MODEL,
                ),
            )
        except Exception:
            logger.exception(
                'Error while initializing Generic LLM',
                extra={'url': self._config.generic_llm_base_url},
            )
            return None

    def _register_builtin_functions(self) -> None:
        """Register built-in functions with all services."""
        for service in self.service_map.values():
            service.register_function('draw_image', self.draw_image)
            service.register_function('get_image', self.get_image)

    def register_function(
        self,
        function_name: str | None,
        handler: FunctionCallHandler,
        *,
        cancel_on_interruption: bool = True,
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

    async def get_image(self, params: FunctionCallParams) -> None:
        """Get an image from the video stream based on a question."""
        prompt = params.arguments['prompt']
        source = params.arguments['source']
        await params.llm.push_frame(
            UserImageRequestFrame(
                user_id='-',
                text=prompt,
                video_source=source,
                append_to_context=True,
            ),
            FrameDirection.UPSTREAM,
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Mirror input images in output stream."""
        await super().process_frame(frame, direction)

        if isinstance(frame, InputImageRawFrame):
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
                    ),
                ),
            )

        await super().push_frame(frame, direction)

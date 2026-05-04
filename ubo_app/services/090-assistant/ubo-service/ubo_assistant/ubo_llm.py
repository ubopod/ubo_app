"""LLM service that wraps multiple LLM services allowing switching between them."""

import json
import os
from dataclasses import dataclass

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
from pipecat.services.cerebras.llm import CerebrasLLMService
from pipecat.services.google.vertex.llm import GoogleVertexLLMService
from pipecat.services.llm_service import (
    FunctionCallHandler,
    FunctionCallParams,
    LLMService,
)
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.xai.llm import GrokLLMService
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    AssistanceTextFrame,
)

from ubo_assistant.constants import IS_RPI
from ubo_assistant.image_frame import ImageGenFrame
from ubo_assistant.switch import UboLLMSwitchService, make_empty_llm_settings

DEFAULT_GENERIC_LLM_MODEL = os.environ.get('DEFAULT_LLM_GENERIC_MODEL', 'gpt-4.1')


@dataclass
class LLMServiceConfig:
    """Configuration for LLM services."""

    google_credentials: str | None = None
    openai_api_key: str | None = None
    grok_api_key: str | None = None
    cerebras_api_key: str | None = None
    ollama_onprem_url: str | None = None
    generic_llm_base_url: str | None = None
    generic_llm_api_key: str | None = None
    generic_llm_model: str | None = None


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

        # Initialize all services
        self.google_vertex_llm = self._create_google_vertex_service()
        self.openai_llm = self._create_openai_service()
        self.grok_llm = self._create_grok_service()
        self.cerebras_llm = self._create_cerebras_service()
        self.ollama_llm = self._create_ollama_service()
        self.ollama_onprem_llm = self._create_ollama_onprem_service()
        self.generic_llm = GenericLLMProxy()

        # Build services dictionary
        self._services = {
            'google_vertex': self.google_vertex_llm,
            'openai': self.openai_llm,
            'grok': self.grok_llm,
            'cerebras': self.cerebras_llm,
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
        """Set the selected service, refreshing Generic LLM secrets first."""
        if id == 'generic_llm':
            await self._refresh_generic_llm_service()
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

    def _create_openai_service(self) -> OpenAILLMService | None:
        """Create OpenAI LLM service if API key is provided."""
        if not self._config.openai_api_key:
            return None

        try:
            return OpenAILLMService(
                api_key=self._config.openai_api_key,
                settings=OpenAILLMService.Settings(
                    model='gpt-4o-mini',  # Vision-capable model for image_url support
                ),
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
                settings=GrokLLMService.Settings(model='grok-4-0709'),
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
                    model='qwen-3-235b-a22b-instruct-2507',
                    temperature=0.7,
                    max_completion_tokens=1000,
                ),
            )
        except Exception:
            logger.exception('Error while initializing Cerebras LLM')
            return None

    def _create_ollama_service(self) -> OLLamaLLMService | None:
        """Create local Ollama LLM service."""
        try:
            return OLLamaLLMService(
                settings=OLLamaLLMService.Settings(
                    model='gemma3:1b' if IS_RPI else 'gemma3:27b-it-qat',
                ),
            )
        except Exception:
            logger.exception('Error while initializing Ollama LLM')
            return None

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

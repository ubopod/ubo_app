"""LLM service that wraps multiple LLM services allowing switching between them."""

import json
from dataclasses import dataclass

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InputImageRawFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputImageRawFrame,
    UserImageRequestFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.cerebras.llm import CerebrasLLMService
from pipecat.services.google.llm_vertex import GoogleVertexLLMService
from pipecat.services.grok.llm import GrokLLMService
from pipecat.services.llm_service import (
    FunctionCallHandler,
    FunctionCallParams,
    LLMService,
)
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.openai.llm import OpenAILLMService
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    AssistanceTextFrame,
)

from ubo_assistant.constants import IS_RPI
from ubo_assistant.image_frame import ImageGenFrame
from ubo_assistant.switch import UboSwitchService


@dataclass
class LLMServiceConfig:
    """Configuration for LLM services."""

    google_credentials: str | None = None
    openai_api_key: str | None = None
    grok_api_key: str | None = None
    cerebras_api_key: str | None = None
    ollama_onprem_url: str | None = None


class UboLLMService(UboSwitchService[OpenAILLMService], OpenAILLMService):
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

        # Build services dictionary
        self._services = {
            'google_vertex': self.google_vertex_llm,
            'openai': self.openai_llm,
            'grok': self.grok_llm,
            'cerebras': self.cerebras_llm,
            'ollama': self.ollama_llm,
            'ollama_onprem': self.ollama_onprem_llm,
        }

        # Initialize parent classes
        UboSwitchService.__init__(self, client=client, selector=selector)
        LLMService.__init__(self)

        # Register built-in functions
        self._register_builtin_functions()

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
                model='gpt-4o-mini',  # Vision-capable model for image_url support
                api_key=self._config.openai_api_key,
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
                model='grok-4-0709',
                api_key=self._config.grok_api_key,
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
                model='qwen-3-235b-a22b-instruct-2507',
                params=CerebrasLLMService.InputParams(
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
                model='gemma3:1b' if IS_RPI else 'gemma3:27b-it-qat',
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
                model='granite3.3:8b',
                base_url=base_url,
            )
        except Exception:
            logger.exception(
                'Error while initializing remote Ollama LLM',
                extra={'url': self._config.ollama_onprem_url},
            )
            return None

    def _register_builtin_functions(self) -> None:
        """Register built-in functions with all services."""
        for service in self.services.values():
            service.register_function('draw_image', self.draw_image)
            service.register_function('get_image', self.get_image)

    def register_function(
        self,
        function_name: str | None,
        handler: FunctionCallHandler,
        start_callback=None,  # noqa: ANN001
        *,
        cancel_on_interruption: bool = True,
    ) -> None:
        """Register a function with all underlying LLM services.

        This method is called by MCP clients to register external tools.
        """
        super().register_function(
            function_name,
            handler,
            start_callback,
            cancel_on_interruption=cancel_on_interruption,
        )

        for service in self.services.values():
            if service is None:
                continue
            service.register_function(
                function_name,
                handler,
                start_callback,
                cancel_on_interruption=cancel_on_interruption,
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
        await super().push_frame(frame, direction)

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

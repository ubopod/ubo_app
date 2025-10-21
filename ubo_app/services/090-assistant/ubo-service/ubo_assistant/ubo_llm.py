"""LLM service that wraps multiple LLM services allowing switching between them."""

import json

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InputImageRawFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputImageRawFrame,
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


class UboLLMService(UboSwitchService[OpenAILLMService], OpenAILLMService):
    """LLM service that wraps multiple LLM services allowing switching between them."""

    def __init__(
        self,
        client: UboRPCClient,
        *,
        google_credentials: str | None,
        openai_api_key: str | None,
        grok_api_key: str | None,
        cerebras_api_key: str | None,
        ollama_onprem_url: str | None,
        selector: str,
    ) -> None:
        """Initialize LLM service with various services including remote Ollama."""
        try:
            if google_credentials:
                project_id = json.loads(google_credentials).get('project_id')
                self.google_vertex_llm = GoogleVertexLLMService(
                    credentials=google_credentials,
                    params=GoogleVertexLLMService.InputParams(project_id=project_id),
                )
            else:
                self.google_vertex_llm = None
        except Exception as exception:
            logger.exception(
                'Error while initializing Google Vertex LLM',
                extra={'exception': exception},
            )
            self.google_vertex_llm = None

        try:
            if openai_api_key:
                self.openai_llm = OpenAILLMService(
                    model='gpt-3.5-turbo',
                    api_key=openai_api_key,
                )
            else:
                self.openai_llm = None
        except Exception:
            logger.exception('Error while initializing OpenAI LLM')
            self.openai_llm = None

        try:
            if grok_api_key:
                self.grok_llm = GrokLLMService(
                    model='grok-4-0709',
                    api_key=grok_api_key,
                )
            else:
                self.grok_llm = None
        except Exception:
            logger.exception('Error while initializing Grok LLM')
            self.grok_llm = None

        try:
            if cerebras_api_key:
                self.cerebras_llm = CerebrasLLMService(
                    api_key=cerebras_api_key,
                    model='qwen-3-235b-a22b-instruct-2507',
                    params=CerebrasLLMService.InputParams(
                        temperature=0.7,
                        max_completion_tokens=1000,
                    ),
                )
            else:
                self.cerebras_llm = None
        except Exception:
            logger.exception('Error while initializing Cerebras LLM')
            self.cerebras_llm = None

        try:
            self.ollama_llm = OLLamaLLMService(
                model='gemma3:1b' if IS_RPI else 'gemma3:27b-it-qat',
            )
        except Exception:
            logger.exception('Error while initializing Ollama LLM')
            self.ollama_llm = None

        try:
            if ollama_onprem_url:
                # Ollama's OpenAI-compatible API is at /v1 endpoint
                base_url = ollama_onprem_url.rstrip('/') + '/v1'
                self.ollama_onprem_llm = OLLamaLLMService(
                    model='granite3.3:8b',
                    base_url=base_url,
                )
            else:
                self.ollama_onprem_llm = None
        except Exception:
            logger.exception(
                'Error while initializing remote Ollama LLM',
                extra={'url': ollama_onprem_url},
            )
            self.ollama_onprem_llm = None

        self._services = {
            'google_vertex': self.google_vertex_llm,
            'openai': self.openai_llm,
            'grok': self.grok_llm,
            'cerebras': self.cerebras_llm,
            'ollama': self.ollama_llm,
            'ollama_onprem': self.ollama_onprem_llm,
        }

        UboSwitchService.__init__(self, client=client, selector=selector)
        LLMService.__init__(self)

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
        await params.llm.request_image_frame(
            user_id='-',
            video_source=source,
            function_name=params.function_name,
            tool_call_id=params.tool_call_id,
            text_content=prompt,
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

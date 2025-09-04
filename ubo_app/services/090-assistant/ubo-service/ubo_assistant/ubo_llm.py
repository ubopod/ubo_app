"""LLM service that wraps multiple LLM services allowing switching between them."""

import json

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.google.llm_vertex import GoogleVertexLLMService
from pipecat.services.grok.llm import GrokLLMService
from pipecat.services.llm_service import FunctionCallParams, LLMService
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
    ) -> None:
        """Initialize the LLM service with Google, OpenAI, and Ollama LLM services."""
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
            self.ollama_llm = OLLamaLLMService(
                model='gemma3:1b' if IS_RPI else 'gemma3:27b-it-qat',
            )
        except Exception:
            logger.exception('Error while initializing Ollama LLM')
            self.ollama_llm = None

        self._services = {
            'google_vertex': self.google_vertex_llm,
            'openai': self.openai_llm,
            'grok': self.grok_llm,
            'ollama': self.ollama_llm,
        }

        UboSwitchService.__init__(self, client=client)
        LLMService.__init__(self)

        for service in self.services.values():
            service.register_function('draw_image', self.draw_image)
            service.register_function('get_image', self.get_image)

    async def draw_image(self, params: FunctionCallParams) -> None:
        """Generate an image based on a text prompt."""
        await self.push_frame(ImageGenFrame(text=params.arguments['prompt']))

    async def get_image(self, params: FunctionCallParams) -> None:
        """Get an image from the video stream based on a question."""
        _ = params

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

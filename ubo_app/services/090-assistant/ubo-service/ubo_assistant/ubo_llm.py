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
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.openai.llm import OpenAILLMService
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    AssistanceTextFrame,
)

from ubo_assistant.constants import IS_RPI
from ubo_assistant.switch import UboSwitchService


class UboLLMService(UboSwitchService[OpenAILLMService], OpenAILLMService):
    """LLM service that wraps multiple LLM services allowing switching between them."""

    def __init__(
        self,
        client: UboRPCClient,
        *,
        google_credentials: str | None,
        openai_api_key: str | None,
        **kwargs: object,
    ) -> None:
        """Initialize the LLM service with Google, OpenAI, and Ollama LLM services."""
        try:
            if google_credentials:
                project_id = json.loads(google_credentials).get('project_id')
                self.google_llm = GoogleVertexLLMService(
                    credentials=google_credentials,
                    params=GoogleVertexLLMService.InputParams(project_id=project_id),
                )
            else:
                self.google_llm = None
        except Exception:
            logger.exception('Error while initializing Google LLM')
            self.google_llm = None

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
            self.ollama_llm = OLLamaLLMService(
                model='gemma3:1b' if IS_RPI else 'gemma3:27b-it-qat',
            )
        except Exception:
            logger.exception('Error while initializing Ollama LLM')
            self.ollama_llm = None

        self._services = [self.google_llm, self.openai_llm, self.ollama_llm]

        super().__init__(
            client=client,
            model='',
            base_url='',
            api_key='',
            **kwargs,
        )

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

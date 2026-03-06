"""Standalone LLM handler for decoupled LLM completion over gRPC."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMMessagesFrame,
    LLMTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistanceErrorFrame,
    AssistanceTextFrame,
    AssistantCompleteEvent,
    AssistantReportAction,
    Event,
)

if TYPE_CHECKING:
    from pipecat.services.llm_service import LLMService
    from ubo_bindings.client import UboRPCClient

_secrets_cache: dict[str, tuple[float, str | None]] = {}
_SECRETS_TTL = 300  # 5 minutes


async def _get_cached_secret(client: UboRPCClient, key: str) -> str | None:
    if not key:
        return None
    now = time.monotonic()
    if key in _secrets_cache:
        ts, value = _secrets_cache[key]
        if now - ts < _SECRETS_TTL:
            return value
    value = await client.query_secret(key)
    if value is not None:
        _secrets_cache[key] = (now, value)
    return value


class _LLMOutputCollector(FrameProcessor):
    """Collects LLM output frames and dispatches them via gRPC."""

    def __init__(
        self,
        client: UboRPCClient,
        session_id: str,
        assistance_id: str,
    ) -> None:
        super().__init__()
        self._client = client
        self._session_id = session_id
        self._assistance_id = assistance_id
        self._index = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process output frames from the LLM."""
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMTextFrame):
            self._client.dispatch(
                action=Action(
                    assistant_report_action=AssistantReportAction(
                        source_id='standalone_llm',
                        data=AcceptableAssistanceFrame(
                            assistance_text_frame=AssistanceTextFrame(
                                text=frame.text,
                                timestamp=self._client.event_loop.time(),
                                id=self._assistance_id,
                                index=self._index,
                                source='llm_standalone',
                                session_id=self._session_id,
                            ),
                        ),
                    ),
                ),
            )
            self._index += 1

        elif isinstance(frame, LLMFullResponseEndFrame):
            self._client.dispatch(
                action=Action(
                    assistant_report_action=AssistantReportAction(
                        source_id='standalone_llm',
                        data=AcceptableAssistanceFrame(
                            assistance_text_frame=AssistanceTextFrame(
                                text='',
                                timestamp=self._client.event_loop.time(),
                                id=self._assistance_id,
                                index=self._index,
                                source='llm_standalone',
                                session_id=self._session_id,
                                is_last_frame=True,
                            ),
                        ),
                    ),
                ),
            )

        await self.push_frame(frame, direction)


def setup_standalone_llm(client: UboRPCClient) -> None:
    """Subscribe to AssistantCompleteEvent and handle standalone LLM requests."""
    semaphore = asyncio.Semaphore(3)

    def _handle_complete_event(event: Event) -> None:
        complete = event.assistant_complete_event
        if not complete:
            return

        async def _guarded() -> None:
            async with semaphore:
                await _process_completion(client, complete)

        client.event_loop.create_task(_guarded())

    client.subscribe_event(
        event_type=Event(
            assistant_complete_event=AssistantCompleteEvent(),
        ),
        callback=_handle_complete_event,
    )
    logger.info('Standalone LLM handler registered')


async def _process_completion(
    client: UboRPCClient,
    event: AssistantCompleteEvent,
) -> None:
    """Process a standalone LLM completion request."""
    session_id = event.session_id
    assistance_id = uuid.uuid4().hex

    llm_provider = event.llm_provider
    if llm_provider is None:
        _dispatch_error(
            client,
            session_id=session_id,
            assistance_id=assistance_id,
            error='No LLM provider specified',
        )
        return

    llm_name = (llm_provider.name or '').lower()

    try:
        llm_service = await _create_llm_service(client, llm_name)

        if llm_service is None:
            _dispatch_error(
                client,
                session_id=session_id,
                assistance_id=assistance_id,
                error=f"LLM provider '{llm_name}' is not configured or unavailable",
            )
            return

        # Build messages
        messages: list[dict[str, str]] = []
        if event.system_prompt:
            messages.append({'role': 'system', 'content': event.system_prompt})
        messages.append({'role': 'user', 'content': event.text})

        # Create output collector
        collector = _LLMOutputCollector(
            client=client,
            session_id=session_id,
            assistance_id=assistance_id,
        )

        # Build and run a mini pipeline
        pipeline = Pipeline([llm_service, collector])
        task = PipelineTask(
            pipeline,
            params=PipelineParams(),
        )
        runner = PipelineRunner(handle_sigint=False)

        # Queue the messages frame and end frame to the pipeline
        await task.queue_frames(
            [LLMMessagesFrame(messages=messages), EndFrame()],
        )

        await runner.run(task)

    except Exception:
        logger.exception(
            'Error in standalone LLM',
            extra={'session_id': session_id},
        )
        _dispatch_error(
            client,
            session_id=session_id,
            assistance_id=assistance_id,
            error='Internal error during completion',
        )


async def _create_llm_service(  # noqa: C901
    client: UboRPCClient,
    llm_name: str,
) -> LLMService | None:
    """Create a standalone LLM service instance for the given provider."""
    import os

    from ubo_assistant.constants import IS_RPI

    if llm_name == 'ollama':
        from pipecat.services.ollama.llm import OLLamaLLMService

        return OLLamaLLMService(
            model='gemma3:1b' if IS_RPI else 'gemma3:27b-it-qat',
        )

    if llm_name == 'ollama_onprem':
        from pipecat.services.ollama.llm import OLLamaLLMService

        url = await _get_cached_secret(client,
            os.environ.get('OLLAMA_ONPREM_URL_SECRET_ID', ''),
        )
        if url:
            base_url = url.rstrip('/') + '/v1'
            return OLLamaLLMService(
                model='granite3.3:8b',
                base_url=base_url,
            )
        return None

    if llm_name == 'google_vertex':
        from pipecat.services.google.llm_vertex import GoogleVertexLLMService

        credentials = await _get_cached_secret(client,
            os.environ.get('GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID', ''),
        )
        if credentials:
            project_id = json.loads(credentials).get('project_id')
            return GoogleVertexLLMService(
                credentials=credentials,
                project_id=project_id,
            )
        return None

    if llm_name == 'openai':
        from pipecat.services.openai.llm import OpenAILLMService

        api_key = await _get_cached_secret(client,
            os.environ.get('OPENAI_API_KEY_SECRET_ID', ''),
        )
        if api_key:
            return OpenAILLMService(
                model='gpt-4o-mini',
                api_key=api_key,
            )
        return None

    if llm_name == 'grok':
        from pipecat.services.grok.llm import GrokLLMService

        api_key = await _get_cached_secret(client,
            os.environ.get('GROK_API_KEY_SECRET_ID', ''),
        )
        if api_key:
            return GrokLLMService(
                model='grok-4-0709',
                api_key=api_key,
            )
        return None

    if llm_name == 'cerebras':
        from pipecat.services.cerebras.llm import CerebrasLLMService

        api_key = await _get_cached_secret(client,
            os.environ.get('CEREBRAS_API_KEY_SECRET_ID', ''),
        )
        if api_key:
            return CerebrasLLMService(
                model='qwen-3-235b-a22b-instruct-2507',
                api_key=api_key,
            )
        return None

    return None


def _dispatch_error(
    client: UboRPCClient,
    *,
    session_id: str,
    assistance_id: str,
    error: str,
) -> None:
    """Dispatch an error frame back to core."""
    client.dispatch(
        action=Action(
            assistant_report_action=AssistantReportAction(
                source_id='standalone_llm',
                data=AcceptableAssistanceFrame(
                    assistance_error_frame=AssistanceErrorFrame(
                        error=error,
                        timestamp=client.event_loop.time(),
                        id=assistance_id,
                        index=0,
                        session_id=session_id,
                        is_last_frame=True,
                    ),
                ),
            ),
        ),
    )

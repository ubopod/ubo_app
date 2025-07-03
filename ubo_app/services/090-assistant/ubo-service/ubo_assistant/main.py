# ruff: noqa: D101, D102, D103, D105, D107
"""A dynamic conversational AI pipeline using Pipecat framework."""

import asyncio
import os
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EndFrame,
    InputAudioRawFrame,
    StartFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AudioReportSampleEvent,
    Event,
)

from ubo_assistant.ubo_llm import UboLLMService
from ubo_assistant.ubo_stt import UboSTTService
from ubo_assistant.ubo_tts import UboTTSService

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam


class UboProvider(BaseOutputTransport):
    def __init__(
        self,
        params: TransportParams,
        client: UboRPCClient,
        **kwargs: object,
    ) -> None:
        self.client = client
        super().__init__(params, **kwargs)

    async def start(self, frame: StartFrame) -> None:
        self.tasks: list[asyncio.Task] = []
        self.client.subscribe_event(
            Event(audio_report_sample_event=AudioReportSampleEvent()),
            self.queue_sample,
        )
        await super().start(frame)

    async def stop(self, frame: EndFrame) -> None:
        return await super().stop(frame)

    def queue_sample(self, event: Event) -> None:
        if event.audio_report_sample_event:
            audio_frame = event.audio_report_sample_event.sample_speech_recognition
            self.tasks = [task for task in self.tasks if not task.done()]
            self.tasks.append(
                asyncio.create_task(
                    self.push_frame(
                        InputAudioRawFrame(
                            audio=audio_frame,
                            sample_rate=16000,
                            num_channels=1,
                        ),
                    ),
                ),
            )


class Assistant:
    def __init__(self) -> None:
        self.client = UboRPCClient('localhost', 50051)

    def __del__(self) -> None:
        self.client.channel.close()

    async def run(self) -> None:
        vad_analyzer = SileroVADAnalyzer(
            sample_rate=16000,
        )

        ubo_provider = UboProvider(
            params=TransportParams(
                audio_in_enabled=True,
                audio_in_channels=1,
                audio_in_sample_rate=16000,
                vad_enabled=True,
                vad_analyzer=vad_analyzer,
                vad_audio_passthrough=True,
            ),
            client=self.client,
        )

        google_credentials = await self.client.query_secret(
            os.environ['GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID'],
        )

        openai_api_key = await self.client.query_secret(
            os.environ['OPENAI_API_KEY_SECRET_ID'],
        )

        ubo_stt_service = UboSTTService(
            client=self.client,
            google_credentials=google_credentials,
            openai_api_key=openai_api_key,
        )

        ubo_llm_service = UboLLMService(
            client=self.client,
            google_credentials=google_credentials,
            openai_api_key=openai_api_key,
        )

        messages: list[ChatCompletionMessageParam] = [
            {
                'role': 'system',
                'content': 'Please write short and concise answers.',
            },
            {
                'role': 'system',
                'content': """it is going to be read by a simple text to \
speech engine. So please answer only with English letters, numbers and standard \
production like period, comma, colon, single and double quotes, exclamation mark, \
question mark, and dash. Do not use any other special characters or emojis.""",
            },
        ]

        context = OpenAILLMContext(messages)
        context_aggregator = ubo_llm_service.create_context_aggregator(context)

        async def g() -> None:
            while True:
                await asyncio.sleep(5)
                print(context.messages)  # noqa: T201

        self.client.event_loop.create_task(g())

        ubo_tts_service = UboTTSService(
            client=self.client,
            google_credentials=google_credentials,
            openai_api_key=openai_api_key,
        )

        pipeline = Pipeline(
            [
                ubo_provider,
                ubo_stt_service,
                context_aggregator.user(),
                ubo_llm_service,
                ubo_tts_service,
                context_aggregator.assistant(),
            ],
        )

        task = PipelineTask(pipeline, params=PipelineParams(audio_in_sample_rate=16000))
        runner = PipelineRunner(handle_sigint=True)
        await runner.run(task)


def main() -> None:
    try:
        assistant = Assistant()
        asyncio.get_event_loop().run_until_complete(assistant.run())
    except Exception as exception:
        logger.info('An error occurred', extra={'exception': exception})
        raise

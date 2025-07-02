# ruff: noqa: D101, D102, D103, D105, D107, BLE001
"""A dynamic conversational AI pipeline using Pipecat framework."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EmulateUserStartedSpeakingFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.google.llm_vertex import GoogleVertexLLMService
from pipecat.services.google.stt import GoogleSTTService
from pipecat.services.google.tts import GoogleTTSService
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    AssistanceAudioFrame,
    AssistanceTextFrame,
    AudioReportSampleEvent,
    AudioSample,
    Event,
)

from ubo_assistant.constants import IS_RPI
from ubo_assistant.piper import PiperTTSService
from ubo_assistant.switch import UboSwitchService
from ubo_assistant.vosk import VoskSTTService

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam

google_credentials = None
openai_api_key = None


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


class UboSTTService(UboSwitchService[STTService], STTService):
    def __init__(
        self,
        client: UboRPCClient,
        **kwargs: object,
    ) -> None:
        self._assistance_index = 0
        try:
            if google_credentials:
                self.google_stt = GoogleSTTService(
                    credentials=google_credentials,
                    model="long",
                    sample_rate=16000,
                )
            else:
                self.google_stt = None
        except Exception as exception:
            logger.exception(
                "Error while initializing Google STT",
                extra={"exception": exception},
            )
            self.google_stt = None

        try:
            if openai_api_key:
                self.openai_stt = OpenAISTTService(api_key=openai_api_key)
            else:
                self.openai_stt = None
        except Exception as exception:
            logger.exception(
                "Error while initializing OpenAI STT",
                extra={"exception": exception},
            )
            self.openai_stt = None

        try:
            self.vosk_stt = VoskSTTService()
        except Exception as exception:
            logger.info(
                "Error while initializing Vosk STT",
                extra={"exception": exception},
            )
            self.vosk_stt = None

        self._services = [self.google_stt, self.openai_stt, self.vosk_stt]

        super().__init__(
            client=client,
            audio_passthrough=True,
            sample_rate=16000,
            **kwargs,
        )

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        _ = audio
        yield None

    async def push_frame(
        self,
        frame: Frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> None:
        """Dispatch the frame in ubo-app's redux bus if it's audio, image or text."""
        await super().push_frame(frame, direction)

        if isinstance(frame, EmulateUserStartedSpeakingFrame):
            self._reset_assistance()

        if isinstance(frame, InterimTranscriptionFrame):
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


class UboLLMService(UboSwitchService[OpenAILLMService], OpenAILLMService):
    def __init__(
        self,
        client: UboRPCClient,
        **kwargs: object,
    ) -> None:
        try:
            if google_credentials:
                project_id = json.loads(google_credentials).get("project_id")
                self.google_llm = GoogleVertexLLMService(
                    credentials=google_credentials,
                    params=GoogleVertexLLMService.InputParams(project_id=project_id),
                )
            else:
                self.google_llm = None
        except Exception as exception:
            logger.exception(
                "Error while initializing Google LLM",
                extra={"exception": exception},
            )
            self.google_llm = None

        try:
            if openai_api_key:
                self.openai_llm = OpenAILLMService(
                    model="gpt-3.5-turbo",
                    api_key=openai_api_key,
                )
            else:
                self.openai_llm = None
        except Exception as exception:
            logger.exception(
                "Error while initializing OpenAI LLM",
                extra={"exception": exception},
            )
            self.openai_llm = None

        try:
            self.ollama_llm = OLLamaLLMService(
                model="gemma3:1b" if IS_RPI else "gemma3:27b-it-qat",
            )
        except Exception as exception:
            logger.exception(
                "Error while initializing Ollama LLM",
                extra={"exception": exception},
            )
            self.ollama_llm = None

        self._services = [self.google_llm, self.openai_llm, self.ollama_llm]

        super().__init__(
            client=client,
            model="",
            base_url="",
            api_key="",
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


class UboTTSService(UboSwitchService[TTSService], TTSService):
    def __init__(
        self,
        client: UboRPCClient,
        **kwargs: object,
    ) -> None:
        try:
            if google_credentials:
                self.google_tts = GoogleTTSService(credentials=google_credentials)
            else:
                self.google_tts = None
        except Exception as exception:
            logger.exception(
                "Error while initializing Google TTS",
                extra={"exception": exception},
            )
            self.google_tts = None

        try:
            if openai_api_key:
                self.openai_tts = OpenAITTSService(api_key=openai_api_key)
            else:
                self.openai_tts = None
        except Exception as exception:
            logger.exception(
                "Error while initializing OpenAI TTS",
                extra={"exception": exception},
            )
            self.openai_tts = None

        try:
            self.piper_tts = PiperTTSService()
        except Exception as exception:
            logger.info(
                "Error while initializing Piper TTS",
                extra={"exception": exception},
            )
            self.piper_tts = None

        self._services = [self.google_tts, self.openai_tts, self.piper_tts]

        super().__init__(
            client=client,
            model="",
            base_url="",
            api_key="",
            **kwargs,
        )

    async def run_tts(self, text: str) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        _ = text
        yield None

    async def push_frame(
        self,
        frame: Frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> None:
        """Dispatch the frame in ubo-app's redux bus if it's audio, image or text."""
        await super().push_frame(frame, direction)

        if isinstance(frame, TTSStartedFrame):
            self._reset_assistance()

        if isinstance(frame, TTSAudioRawFrame):
            self._report_assistance_frame(
                AcceptableAssistanceFrame(
                    assistance_audio_frame=AssistanceAudioFrame(
                        audio=AudioSample(
                            data=frame.audio,
                            channels=frame.num_channels,
                            rate=frame.sample_rate,
                            width=2,
                        ),
                        timestamp=self.client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._assistance_index,
                    ),
                ),
            )

        if isinstance(frame, TTSStoppedFrame):
            self._report_assistance_frame(
                AcceptableAssistanceFrame(
                    assistance_audio_frame=AssistanceAudioFrame(
                        audio=None,
                        timestamp=self.client.event_loop.time(),
                        id=self._assistance_id,
                        index=self._assistance_index,
                    ),
                ),
            )


class Assistant:
    def __init__(self) -> None:
        self.client = UboRPCClient("localhost", 50051)

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

        ubo_stt_service = UboSTTService(client=self.client)

        ubo_llm_service = UboLLMService(client=self.client)

        messages: list[ChatCompletionMessageParam] = [
            {
                "role": "system",
                "content": "Please write short and concise answers.",
            },
            {
                "role": "system",
                "content": """it is going to be read by a simple text to \
speech engine. So please answer only with English letters, numbers and standard \
production like period, comma, colon, single and double quotes, exclamation mark, \
question mark, and dash. Do not use any other special characters or emojis.""",
            },
        ]

        context = OpenAILLMContext(messages)
        context_aggregator = ubo_llm_service.create_context_aggregator(context)

        async def g():
            while True:
                await asyncio.sleep(5)
                print(context.messages)

        self.client.event_loop.create_task(g())

        ubo_tts_service = UboTTSService(client=self.client)

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
        logger.info("An error occurred", extra={"exception": exception})

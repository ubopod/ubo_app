# ruff: noqa: D101, D102, D103, D105, D107

"""A dynamic conversational AI pipeline using Pipecat framework."""

import asyncio
import os

from loguru import logger
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import Frame
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import WorkerRunner
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import (
    LLMContext,
    LLMContextMessage,
)
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.consumer_processor import ConsumerProcessor
from pipecat.processors.producer_processor import ProducerProcessor
from pipecat.transports.base_transport import TransportParams
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from ubo_bindings.client import UboRPCClient

from ubo_assistant.barge_in import BargeInOnListenSignal
from ubo_assistant.constants import DEFAULT_SYSTEM_MESSAGE, DEFAULT_TOOLS_MESSAGE
from ubo_assistant.end_of_turn import EndOfTurnPhraseDetector
from ubo_assistant.error_notification import attach_error_notifier
from ubo_assistant.image_frame import ImageGenFrame
from ubo_assistant.logging import setup_file_logging
from ubo_assistant.pipecat_debug import attach_whisker_observer
from ubo_assistant.policy_watcher import PolicyWatcher
from ubo_assistant.request_handler import setup_request_handler
from ubo_assistant.silence_user_turn_stop import (
    UboPolicyAwareUserTurnStopStrategy,
)
from ubo_assistant.stop_listening_on_bot_speech import StopListeningOnBotSpeech
from ubo_assistant.stop_talking import StopTalkingOnSignal
from ubo_assistant.ubo_image_generator import UboImageGeneratorService
from ubo_assistant.ubo_input_transport import UboInputTransport
from ubo_assistant.ubo_llm import LLMServiceConfig, UboLLMService
from ubo_assistant.ubo_output_transport import UboOutputTransport
from ubo_assistant.ubo_stt import STTServiceConfig, UboSTTService
from ubo_assistant.ubo_tts import TTSServiceConfig, UboTTSService


class Assistant:
    def __init__(self) -> None:
        self.client = UboRPCClient('localhost', 50051)

    def __del__(self) -> None:
        self.client.channel.close()

    async def run(self) -> None:  # noqa: PLR0915
        vad_processor = VADProcessor(
            vad_analyzer=SileroVADAnalyzer(sample_rate=16000),
        )

        ubo_input_transport = UboInputTransport(
            params=TransportParams(
                audio_in_enabled=True,
                audio_in_channels=1,
                audio_in_sample_rate=16000,
                video_in_enabled=True,
            ),
            client=self.client,
        )

        ubo_output_transport = UboOutputTransport(
            params=TransportParams(
                audio_out_enabled=True,
                audio_out_channels=2,
                audio_out_sample_rate=48000,
                video_out_enabled=True,
                video_out_width=1024,
                video_out_height=1024,
                video_out_color_format='RGB',
                video_out_bitrate=60_000_000,
                video_out_is_live=True,
            ),
            client=self.client,
        )

        google_credentials = await self.client.query_secret(
            os.environ['GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID'],
        )

        google_api_key = await self.client.query_secret(
            os.environ['GOOGLE_API_KEY_SECRET_ID'],
        )

        openai_api_key = await self.client.query_secret(
            os.environ['OPENAI_API_KEY_SECRET_ID'],
        )

        grok_api_key = await self.client.query_secret(
            os.environ['GROK_API_KEY_SECRET_ID'],
        )

        cerebras_api_key = await self.client.query_secret(
            os.environ['CEREBRAS_API_KEY_SECRET_ID'],
        )

        anthropic_api_key = await self.client.query_secret(
            os.environ['ANTHROPIC_API_KEY_SECRET_ID'],
        )

        qwen_api_key = await self.client.query_secret(
            os.environ['QWEN_API_KEY_SECRET_ID'],
        )

        deepseek_api_key = await self.client.query_secret(
            os.environ['DEEPSEEK_API_KEY_SECRET_ID'],
        )

        openrouter_api_key = await self.client.query_secret(
            os.environ['OPENROUTER_API_KEY_SECRET_ID'],
        )

        mistral_api_key = await self.client.query_secret(
            os.environ['MISTRAL_API_KEY_SECRET_ID'],
        )

        venice_api_key = await self.client.query_secret(
            os.environ['VENICE_API_KEY_SECRET_ID'],
        )

        elevenlabs_api_key = await self.client.query_secret(
            os.environ['ELEVENLABS_API_KEY_SECRET_ID'],
        )

        elevenlabs_voice_id = await self.client.query_secret(
            os.environ['ELEVENLABS_VOICE_ID'],
        )

        deepgram_api_key = await self.client.query_secret(
            os.environ['DEEPGRAM_API_KEY_SECRET_ID'],
        )

        assemblyai_api_key = await self.client.query_secret(
            os.environ['ASSEMBLYAI_API_KEY_SECRET_ID'],
        )

        rime_api_key = await self.client.query_secret(
            os.environ['RIME_API_KEY_SECRET_ID'],
        )

        ollama_onprem_url = await self.client.query_secret(
            os.environ['OLLAMA_ONPREM_URL_SECRET_ID'],
        )

        generic_llm_base_url = await self.client.query_secret(
            os.environ['GENERIC_LLM_BASE_URL_SECRET_ID'],
        )

        generic_llm_api_key = await self.client.query_secret(
            os.environ['GENERIC_LLM_API_KEY_SECRET_ID'],
        )

        generic_llm_model = await self.client.query_secret(
            os.environ['GENERIC_LLM_MODEL_SECRET_ID'],
        )

        ubo_stt_service = UboSTTService(
            client=self.client,
            config=STTServiceConfig(
                openai_api_key=openai_api_key,
                deepgram_api_key=deepgram_api_key,
                assemblyai_api_key=assemblyai_api_key,
                venice_api_key=venice_api_key,
                mistral_api_key=mistral_api_key,
                elevenlabs_api_key=elevenlabs_api_key,
            ),
            google_credentials=google_credentials,
            selector='state.assistant.selected_stt',
        )

        policy_watcher = PolicyWatcher(self.client)
        silence_user_turn_stop_strategy = UboPolicyAwareUserTurnStopStrategy(
            client=self.client,
            policy_watcher=policy_watcher,
        )
        end_of_turn_detector = EndOfTurnPhraseDetector(
            client=self.client,
            policy_watcher=policy_watcher,
            user_turn_stop_strategy=silence_user_turn_stop_strategy,
        )
        barge_in_on_listen = BargeInOnListenSignal(client=self.client)
        stop_listening_on_bot_speech = StopListeningOnBotSpeech(client=self.client)

        ubo_llm_service = UboLLMService(
            client=self.client,
            config=LLMServiceConfig(
                google_credentials=google_credentials,
                openai_api_key=openai_api_key,
                grok_api_key=grok_api_key,
                cerebras_api_key=cerebras_api_key,
                anthropic_api_key=anthropic_api_key,
                qwen_api_key=qwen_api_key,
                deepseek_api_key=deepseek_api_key,
                openrouter_api_key=openrouter_api_key,
                mistral_api_key=mistral_api_key,
                venice_api_key=venice_api_key,
                ollama_onprem_url=ollama_onprem_url,
                generic_llm_base_url=generic_llm_base_url,
                generic_llm_api_key=generic_llm_api_key,
                generic_llm_model=generic_llm_model,
            ),
            selector='state.assistant.selected_llm',
        )

        messages: list[LLMContextMessage] = [{
            'role': 'system',
            'content': DEFAULT_SYSTEM_MESSAGE + DEFAULT_TOOLS_MESSAGE,
        }]

        tools = ToolsSchema(standard_tools=[])
        context = LLMContext(messages, tools)
        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=UserTurnStrategies(
                    stop=[silence_user_turn_stop_strategy],
                ),
            ),
        )
        user_aggregator = context_aggregator.user()
        assistant_aggregator = context_aggregator.assistant()

        # Needs the user aggregator (to clear an already-aggregated transcript) and
        # a pipeline slot downstream of STT (to swallow the ones still arriving).
        stop_talking_on_signal = StopTalkingOnSignal(
            client=self.client,
            user_aggregator=user_aggregator,
        )

        async def g() -> None:
            while True:
                await asyncio.sleep(10)
                messages_list = context.get_messages()
                if len(messages_list) > 10:  # noqa: PLR2004
                    logger.debug('...trimmed messages')
                for message in messages_list[-10:]:
                    logger.debug('Message: {extra}',
                                 extra={'mesg:': str(message)[:300]},
                                )
                # Log current tools from context
                tools_schema = context.tools
                if tools_schema and hasattr(tools_schema, 'standard_tools'):
                    tool_names = [tool.name for tool in tools_schema.standard_tools]
                    logger.debug(
                        'Current tools in context {extra}',
                        extra={'tool_count': len(tool_names), 'tools': tool_names},
                    )
                else:
                    logger.debug('No tools currently in context')

        self.client.event_loop.create_task(g())

        ubo_tts_service = UboTTSService(
            client=self.client,
            config=TTSServiceConfig(
                openai_api_key=openai_api_key,
                elevenlabs_api_key=elevenlabs_api_key,
                elevenlabs_voice_id=elevenlabs_voice_id,
                rime_api_key=rime_api_key,
                venice_api_key=venice_api_key,
                mistral_api_key=mistral_api_key,
            ),
            google_credentials=google_credentials,
            selector='state.assistant.selected_tts',
        )

        ubo_image_generator_service = UboImageGeneratorService(
            client=self.client,
            google_api_key=google_api_key,
            openai_api_key=openai_api_key,
            venice_api_key=venice_api_key,
            selector='state.assistant.selected_image_generator',
        )

        # Handle decoupled programmatic STT/LLM/TTS pipeline requests, isolated
        # from the live conversation pipeline below.
        setup_request_handler(self.client)

        async def is_image_gen_frame(frame: Frame) -> bool:
            return isinstance(frame, ImageGenFrame)

        image_producer = ProducerProcessor(
            filter=is_image_gen_frame,
            passthrough=False,
        )
        image_consumer = ConsumerProcessor(producer=image_producer)
        pipeline = Pipeline(
            [
                ubo_input_transport,
                ParallelPipeline(
                    [
                        vad_processor,
                        barge_in_on_listen,
                        ubo_stt_service,
                        # After STT so it sees the transcription frames of a
                        # discarded turn and can withhold them from the
                        # aggregator (and from end-of-turn detection).
                        stop_talking_on_signal,
                        end_of_turn_detector,
                        user_aggregator,
                        ubo_llm_service,
                        image_producer,
                        ubo_tts_service,
                        # After TTS so it sees the downstream TTSStartedFrame —
                        # stop listening the instant the bot starts talking.
                        stop_listening_on_bot_speech,
                    ],
                    [
                        image_consumer,
                        ubo_image_generator_service,
                    ],
                ),
                ubo_output_transport,
                assistant_aggregator,
            ],
        )

        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(audio_in_sample_rate=16000),
            cancel_on_idle_timeout=False,
        )
        attach_error_notifier(worker, self.client)
        whisker_sink = attach_whisker_observer(worker)
        runner = WorkerRunner(handle_sigint=True)
        if whisker_sink is not None:
            # The sink is a Whisker worker; its start() opens the recording
            # file / WS server. Without registering it the observer records
            # nothing.
            await runner.add_workers(whisker_sink)

        await runner.run(worker)


def main() -> None:
    try:
        setup_file_logging()
        assistant = Assistant()
        asyncio.get_event_loop().run_until_complete(assistant.run())
    except Exception as exception:
        logger.info('An error occurred', extra={'exception': exception})
        raise

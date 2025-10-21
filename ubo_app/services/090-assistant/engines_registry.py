"""Engines registry."""

from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.assemblyai import AssemblyAIEngine
from ubo_app.engines.cerebras import CerebrasEngine
from ubo_app.engines.deepgram import DeepgramEngine
from ubo_app.engines.elevenlabs import ElevenLabsEngine
from ubo_app.engines.google import GoogleEngine
from ubo_app.engines.google_cloud import GoogleCloudEngine
from ubo_app.engines.grok import GrokEngine
from ubo_app.engines.ollama import OllamaEngine
from ubo_app.engines.ollama_onprem import OllamaOnPremEngine
from ubo_app.engines.openai import OpenAIEngine
from ubo_app.engines.piper import PiperEngine
from ubo_app.engines.rime import RimeEngine
from ubo_app.engines.vosk import VoskEngine
from ubo_app.store.services.assistant import (
    AssistantImageGeneratorName,
    AssistantLLMName,
    AssistantSTTName,
    AssistantTTSName,
)

STT_ENGINES: dict[AssistantSTTName, AIProviderMixin] = {
    AssistantSTTName.VOSK: VoskEngine(),
    AssistantSTTName.GOOGLE: GoogleCloudEngine(label='Google (continuous)'),
    AssistantSTTName.GOOGLE_SEGMENTED: GoogleCloudEngine(label='Google (segmented)'),
    AssistantSTTName.OPENAI: OpenAIEngine(),
    AssistantSTTName.DEEPGRAM: DeepgramEngine(),
    AssistantSTTName.ASSEMBLYAI: AssemblyAIEngine(),
}

LLM_ENGINES: dict[AssistantLLMName, AIProviderMixin] = {
    AssistantLLMName.OLLAMA: OllamaEngine(),
    AssistantLLMName.OLLAMA_ONPREM: OllamaOnPremEngine(),
    AssistantLLMName.GOOGLE: GoogleCloudEngine(label='Google Vertex'),
    AssistantLLMName.GROK: GrokEngine(),
    AssistantLLMName.CEREBRAS: CerebrasEngine(),
    AssistantLLMName.OPENAI: OpenAIEngine(),
}

TTS_ENGINES: dict[AssistantTTSName, AIProviderMixin] = {
    AssistantTTSName.PIPER: PiperEngine(),
    AssistantTTSName.GOOGLE: GoogleCloudEngine(label='Google'),
    AssistantTTSName.OPENAI: OpenAIEngine(),
    AssistantTTSName.ELEVENLABS: ElevenLabsEngine(),
    AssistantTTSName.RIME: RimeEngine(),
}

IMAGE_GENERATOR_ENGINES: dict[
    AssistantImageGeneratorName,
    AIProviderMixin,
] = {
    AssistantImageGeneratorName.GOOGLE: GoogleEngine(),
    AssistantImageGeneratorName.OPENAI: OpenAIEngine(),
}

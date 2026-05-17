"""Engines registry."""

from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.anthropic import AnthropicEngine
from ubo_app.engines.assemblyai import AssemblyAIEngine
from ubo_app.engines.cerebras import CerebrasEngine
from ubo_app.engines.deepgram import DeepgramEngine
from ubo_app.engines.deepseek import DeepSeekEngine
from ubo_app.engines.elevenlabs import ElevenLabsEngine
from ubo_app.engines.generic_llm import GenericLLMEngine
from ubo_app.engines.google import GoogleEngine
from ubo_app.engines.google_cloud import GoogleCloudEngine
from ubo_app.engines.grok import GrokEngine
from ubo_app.engines.kokoro import KokoroEngine
from ubo_app.engines.mistral import MistralEngine
from ubo_app.engines.ollama import OllamaEngine
from ubo_app.engines.ollama_onprem import OllamaOnPremEngine
from ubo_app.engines.openai import OpenAIEngine
from ubo_app.engines.openrouter import OpenRouterEngine
from ubo_app.engines.piper import PiperEngine
from ubo_app.engines.qwen import QwenEngine
from ubo_app.engines.rime import RimeEngine
from ubo_app.engines.venice import VeniceEngine
from ubo_app.engines.vosk import VoskEngine
from ubo_app.store.services.assistant import (
    AssistantImageGeneratorName,
    AssistantLLMName,
    AssistantSTTName,
    AssistantTTSName,
)

# Single shared Venice engine reused across STT/LLM/TTS dicts — one API key
# setup flow handles all three modalities (mirrors OpenAIEngine reuse).
_VENICE_ENGINE = VeniceEngine()

STT_ENGINES: dict[AssistantSTTName, AIProviderMixin] = {
    AssistantSTTName.VOSK: VoskEngine(),
    AssistantSTTName.GOOGLE: GoogleCloudEngine(label='Google (continuous)'),
    AssistantSTTName.GOOGLE_SEGMENTED: GoogleCloudEngine(label='Google (segmented)'),
    AssistantSTTName.OPENAI: OpenAIEngine(),
    AssistantSTTName.DEEPGRAM: DeepgramEngine(),
    AssistantSTTName.ASSEMBLYAI: AssemblyAIEngine(),
    AssistantSTTName.VENICE: _VENICE_ENGINE,
}

LLM_ENGINES: dict[AssistantLLMName, AIProviderMixin] = {
    AssistantLLMName.OLLAMA: OllamaEngine(),
    AssistantLLMName.OLLAMA_ONPREM: OllamaOnPremEngine(),
    AssistantLLMName.GOOGLE: GoogleCloudEngine(label='Google Vertex'),
    AssistantLLMName.GROK: GrokEngine(),
    AssistantLLMName.CEREBRAS: CerebrasEngine(),
    AssistantLLMName.OPENAI: OpenAIEngine(),
    AssistantLLMName.ANTHROPIC: AnthropicEngine(),
    AssistantLLMName.QWEN: QwenEngine(),
    AssistantLLMName.DEEPSEEK: DeepSeekEngine(),
    AssistantLLMName.OPENROUTER: OpenRouterEngine(),
    AssistantLLMName.MISTRAL: MistralEngine(),
    AssistantLLMName.VENICE: _VENICE_ENGINE,
    AssistantLLMName.GENERIC: GenericLLMEngine(),
}

TTS_ENGINES: dict[AssistantTTSName, AIProviderMixin] = {
    AssistantTTSName.PIPER: PiperEngine(),
    AssistantTTSName.KOKORO: KokoroEngine(),
    AssistantTTSName.GOOGLE: GoogleCloudEngine(label='Google'),
    AssistantTTSName.OPENAI: OpenAIEngine(),
    AssistantTTSName.ELEVENLABS: ElevenLabsEngine(),
    AssistantTTSName.RIME: RimeEngine(),
    AssistantTTSName.VENICE: _VENICE_ENGINE,
}

IMAGE_GENERATOR_ENGINES: dict[
    AssistantImageGeneratorName,
    AIProviderMixin,
] = {
    AssistantImageGeneratorName.GOOGLE: GoogleEngine(),
    AssistantImageGeneratorName.OPENAI: OpenAIEngine(),
}

"""Engines registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
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

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin

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
    AssistantLLMName.GOOGLE: GoogleCloudEngine(label='Google'),
    AssistantLLMName.GROK: GrokEngine(),
    AssistantLLMName.CEREBRAS: CerebrasEngine(),
    AssistantLLMName.OPENAI: OpenAIEngine(),
    AssistantLLMName.ANTHROPIC: AnthropicEngine(),
    AssistantLLMName.QWEN: QwenEngine(),
    AssistantLLMName.DEEPSEEK: DeepSeekEngine(),
    AssistantLLMName.OPENROUTER: OpenRouterEngine(),
    AssistantLLMName.MISTRAL: MistralEngine(),
    AssistantLLMName.VENICE: _VENICE_ENGINE,
    # The id-less GenericLLMEngine is the "Add Generic LLM" adder: it is
    # permanently not-setup and its setup flow registers a new named
    # provider. Named provider instances are built dynamically from
    # ``state.assistant.generic_llm_providers`` in setup.py menus.
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


_EngineName = TypeVar('_EngineName')


def is_engine_configured(
    registry: Mapping[_EngineName, AIProviderMixin],
    selected: _EngineName,
    provider_setup_status: Mapping[str, bool],
) -> bool:
    """Return True if *selected* is set up — or absent from *registry*.

    ``provider_setup_status`` is keyed by ``engine.name`` (see the
    ``AssistantUpdateProvidersAction`` reducer), which is NOT the enum value for
    every engine (e.g. the Google STT variants both map to ``'google_cloud'``),
    so the lookup must go through the engine instance. Unknown selections (e.g.
    the dynamic generic-LLM selection) return True so callers leave them alone.
    """
    engine = registry.get(selected)
    if engine is None:
        return True
    return provider_setup_status.get(engine.name, True)


def first_configured_engine(
    registry: Mapping[_EngineName, AIProviderMixin],
    provider_setup_status: Mapping[str, bool],
    *,
    skip: tuple[_EngineName, ...] = (),
) -> _EngineName | None:
    """Return the first set-up engine in *registry*, local engines first.

    Local (offline) engines — Vosk, Ollama, Piper, Kokoro — are preferred over
    cloud (``RemoteMixin``) engines, mirroring the UI's local/cloud split. The
    sort is stable, so registry order breaks ties within each group. Returns
    ``None`` when nothing in *registry* is configured.
    """
    entries = [(name, e) for name, e in registry.items() if name not in skip]
    entries.sort(key=lambda item: isinstance(item[1], RemoteMixin))
    return next(
        (
            name
            for name, e in entries
            if provider_setup_status.get(e.name, False)
        ),
        None,
    )

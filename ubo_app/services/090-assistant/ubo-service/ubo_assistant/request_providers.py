"""Single-provider construction for one-shot programmatic pipeline requests.

The live pipeline's ``UboSTTService``/``UboLLMService``/``UboTTSService`` switchers
hold every provider and are driven by store autoruns. A programmatic request instead
needs exactly one provider, built fresh, so these helpers construct a single pipecat
service for a given provider id — mirroring the ``_create_*_service`` construction in
``ubo_stt``/``ubo_llm``/``ubo_tts`` (Pipecat 1.0 APIs).

Secrets are queried per call so freshly entered keys take effect; the Vosk model load
is offloaded to a thread so it never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pipecat.services.llm_service import LLMService
    from pipecat.services.stt_service import STTService
    from pipecat.services.tts_service import TTSService
    from ubo_bindings.client import UboRPCClient

VENICE_BASE_URL = 'https://api.venice.ai/api/v1'
_GOOGLE_CREDENTIALS_ENV = 'GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID'
_DEFAULT_VENICE_STT_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_STT_MODEL',
    'nvidia/parakeet-tdt-0.6b-v3',
)
_DEFAULT_VENICE_TTS_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_TTS_MODEL',
    'tts-kokoro',
)
_DEFAULT_VENICE_TTS_VOICE = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_TTS_VOICE',
    'af_sky',
)


async def _secret(client: UboRPCClient, env_var: str) -> str | None:
    """Resolve the secret whose id is held by ``env_var``."""
    key = os.environ.get(env_var)
    if not key:
        return None
    return await client.query_secret(key)


async def _build_stt(  # noqa: C901
    provider_id: str,
    client: UboRPCClient,
) -> STTService | None:
    if provider_id == 'vosk':
        from ubo_assistant.vosk import DEFAULT_VOSK_MODEL_ID, VoskSTTService

        # The Vosk model load is blocking — keep it off the event loop.
        return await asyncio.to_thread(VoskSTTService, model_id=DEFAULT_VOSK_MODEL_ID)

    if provider_id in ('google', 'google_segmented'):
        credentials = await _secret(client, _GOOGLE_CREDENTIALS_ENV)
        if not credentials:
            return None
        from pipecat.services.google.stt import GoogleSTTService

        if provider_id == 'google_segmented':
            from ubo_assistant.segmented_googlestt import SegmentedGoogleSTTService

            return SegmentedGoogleSTTService(
                credentials=credentials,
                sample_rate=16000,
                settings=GoogleSTTService.Settings(model='long'),
            )
        return GoogleSTTService(
            credentials=credentials,
            sample_rate=16000,
            settings=GoogleSTTService.Settings(model='long'),
        )

    if provider_id == 'openai':
        api_key = await _secret(client, 'OPENAI_API_KEY_SECRET_ID')
        if not api_key:
            return None
        from pipecat.services.openai.stt import OpenAISTTService

        return OpenAISTTService(api_key=api_key)

    if provider_id == 'deepgram':
        api_key = await _secret(client, 'DEEPGRAM_API_KEY_SECRET_ID')
        if not api_key:
            return None
        from pipecat.services.deepgram.stt import DeepgramSTTService

        return DeepgramSTTService(
            api_key=api_key,
            settings=DeepgramSTTService.Settings(
                model='nova-3',
                language='multi',
                smart_format=True,
            ),
        )

    if provider_id == 'assemblyai':
        api_key = await _secret(client, 'ASSEMBLYAI_API_KEY_SECRET_ID')
        if not api_key:
            return None
        from pipecat.services.assemblyai.models import AssemblyAIConnectionParams
        from pipecat.services.assemblyai.stt import AssemblyAISTTService

        return AssemblyAISTTService(
            api_key=api_key,
            vad_force_turn_endpoint=False,
            connection_params=AssemblyAIConnectionParams(
                end_of_turn_confidence_threshold=0.7,
                min_end_of_turn_silence_when_confident=160,
                max_turn_silence=2400,
            ),
        )

    if provider_id == 'venice':
        api_key = await _secret(client, 'VENICE_API_KEY_SECRET_ID')
        if not api_key:
            return None
        from ubo_assistant.venice_stt import VeniceSTTService

        return VeniceSTTService(
            api_key=api_key,
            base_url=VENICE_BASE_URL,
            settings=VeniceSTTService.Settings(model=_DEFAULT_VENICE_STT_MODEL),
        )

    return None


async def _build_llm(
    provider_id: str,
    model: str,
    client: UboRPCClient,
) -> LLMService | None:
    if provider_id == 'ollama':
        from pipecat.services.ollama.llm import OLLamaLLMService

        return OLLamaLLMService(settings=OLLamaLLMService.Settings(model=model))

    if provider_id == 'ollama_onprem':
        url = await _secret(client, 'OLLAMA_ONPREM_URL_SECRET_ID')
        if not url:
            return None
        from pipecat.services.ollama.llm import OLLamaLLMService

        return OLLamaLLMService(
            settings=OLLamaLLMService.Settings(model=model),
            base_url=url.rstrip('/') + '/v1',
        )

    if provider_id == 'google_vertex':
        credentials = await _secret(client, _GOOGLE_CREDENTIALS_ENV)
        if not credentials:
            return None
        from pipecat.services.google.vertex.llm import GoogleVertexLLMService

        return GoogleVertexLLMService(
            credentials=credentials,
            project_id=json.loads(credentials).get('project_id'),
        )

    if provider_id == 'generic_llm':
        base_url = await _secret(client, 'GENERIC_LLM_BASE_URL_SECRET_ID')
        api_key = await _secret(client, 'GENERIC_LLM_API_KEY_SECRET_ID')
        if not (base_url and api_key):
            return None
        from pipecat.services.openai.llm import OpenAILLMService

        return OpenAILLMService(
            api_key=api_key,
            base_url=base_url,
            settings=OpenAILLMService.Settings(model=model),
        )

    # Single-API-key cloud LLM providers, keyed by (env var, builder).
    api_key_envs = {
        'openai': 'OPENAI_API_KEY_SECRET_ID',
        'grok': 'GROK_API_KEY_SECRET_ID',
        'cerebras': 'CEREBRAS_API_KEY_SECRET_ID',
        'anthropic': 'ANTHROPIC_API_KEY_SECRET_ID',
        'qwen': 'QWEN_API_KEY_SECRET_ID',
        'deepseek': 'DEEPSEEK_API_KEY_SECRET_ID',
        'openrouter': 'OPENROUTER_API_KEY_SECRET_ID',
        'mistral': 'MISTRAL_API_KEY_SECRET_ID',
        'venice': 'VENICE_API_KEY_SECRET_ID',
    }
    env_var = api_key_envs.get(provider_id)
    if env_var is None:
        return None
    api_key = await _secret(client, env_var)
    if not api_key:
        return None
    return _construct_cloud_llm(provider_id, model, api_key)


def _construct_cloud_llm(
    provider_id: str,
    model: str,
    api_key: str,
) -> LLMService | None:
    if provider_id == 'openai':
        from pipecat.services.openai.llm import OpenAILLMService

        return OpenAILLMService(
            api_key=api_key,
            settings=OpenAILLMService.Settings(model=model),
        )
    if provider_id == 'grok':
        from pipecat.services.xai.llm import GrokLLMService

        return GrokLLMService(
            api_key=api_key,
            settings=GrokLLMService.Settings(model=model),
        )
    if provider_id == 'cerebras':
        from pipecat.services.cerebras.llm import CerebrasLLMService

        return CerebrasLLMService(
            api_key=api_key,
            settings=CerebrasLLMService.Settings(
                model=model,
                temperature=0.7,
                max_completion_tokens=1000,
            ),
        )
    if provider_id == 'anthropic':
        from pipecat.services.anthropic.llm import AnthropicLLMService

        return AnthropicLLMService(
            api_key=api_key,
            settings=AnthropicLLMService.Settings(model=model),
        )
    if provider_id == 'qwen':
        from pipecat.services.qwen.llm import QwenLLMService

        return QwenLLMService(
            api_key=api_key,
            settings=QwenLLMService.Settings(model=model),
        )
    if provider_id == 'deepseek':
        from pipecat.services.deepseek.llm import DeepSeekLLMService

        return DeepSeekLLMService(
            api_key=api_key,
            settings=DeepSeekLLMService.Settings(model=model),
        )
    if provider_id == 'openrouter':
        from pipecat.services.openrouter.llm import OpenRouterLLMService

        return OpenRouterLLMService(
            api_key=api_key,
            settings=OpenRouterLLMService.Settings(model=model),
        )
    if provider_id == 'mistral':
        from pipecat.services.mistral.llm import MistralLLMService

        return MistralLLMService(
            api_key=api_key,
            settings=MistralLLMService.Settings(model=model),
        )
    if provider_id == 'venice':
        from pipecat.services.openai.llm import OpenAILLMService

        return OpenAILLMService(
            api_key=api_key,
            base_url=VENICE_BASE_URL,
            settings=OpenAILLMService.Settings(model=model),
        )
    return None


async def _build_tts(  # noqa: C901, PLR0912
    provider_id: str,
    client: UboRPCClient,
) -> TTSService | None:
    if provider_id == 'piper':
        from ubo_assistant.piper import DEFAULT_PIPER_VOICE_ID, PiperTTSService

        return PiperTTSService(voice_id=DEFAULT_PIPER_VOICE_ID)

    if provider_id == 'kokoro':
        from ubo_assistant.kokoro import (
            DEFAULT_KOKORO_VOICE_ID,
            KokoroTTSService,
        )
        from ubo_assistant.kokoro import MODEL_PATH as KOKORO_MODEL_PATH
        from ubo_assistant.kokoro import VOICES_PATH as KOKORO_VOICES_PATH

        if not (KOKORO_MODEL_PATH.exists() and KOKORO_VOICES_PATH.exists()):
            return None
        return KokoroTTSService(voice_id=DEFAULT_KOKORO_VOICE_ID)

    if provider_id == 'google':
        credentials = await _secret(client, _GOOGLE_CREDENTIALS_ENV)
        if not credentials:
            return None
        from pipecat.services.google.tts import GoogleTTSService

        return GoogleTTSService(credentials=credentials)

    if provider_id == 'openai':
        api_key = await _secret(client, 'OPENAI_API_KEY_SECRET_ID')
        if not api_key:
            return None
        from pipecat.services.openai.tts import OpenAITTSService

        return OpenAITTSService(api_key=api_key)

    if provider_id == 'elevenlabs':
        api_key = await _secret(client, 'ELEVENLABS_API_KEY_SECRET_ID')
        voice_id = await _secret(client, 'ELEVENLABS_VOICE_ID')
        if not (api_key and voice_id):
            return None
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        return ElevenLabsTTSService(
            api_key=api_key,
            voice_id=voice_id,
            sample_rate=24000,
            model='eleven_turbo_v2_5',
            enable_logging=True,
        )

    if provider_id == 'rime':
        api_key = await _secret(client, 'RIME_API_KEY_SECRET_ID')
        if not api_key:
            return None
        from pipecat.services.rime.tts import RimeTTSService
        from pipecat.transcriptions.language import Language

        return RimeTTSService(
            api_key=api_key,
            voice_id='antoine',
            model='mistv2',
            params=RimeTTSService.InputParams(
                language=Language.EN,
                speed_alpha=1.0,
                reduce_latency=False,
                pause_between_brackets=True,
                phonemize_between_brackets=False,
            ),
        )

    if provider_id == 'venice':
        api_key = await _secret(client, 'VENICE_API_KEY_SECRET_ID')
        if not api_key:
            return None
        from ubo_assistant.venice_tts import VeniceTTSService

        return VeniceTTSService(
            api_key=api_key,
            base_url=VENICE_BASE_URL,
            model=_DEFAULT_VENICE_TTS_MODEL,
            voice=_DEFAULT_VENICE_TTS_VOICE,
        )

    return None


async def build_stt_service(
    provider_id: str,
    *,
    client: UboRPCClient,
) -> STTService | None:
    """Construct the STT service for ``provider_id``, or ``None`` if unavailable."""
    try:
        return await _build_stt(provider_id, client)
    except Exception:
        logger.exception('Failed to build STT service', extra={'provider': provider_id})
        return None


async def build_llm_service(
    provider_id: str,
    *,
    model: str,
    client: UboRPCClient,
) -> LLMService | None:
    """Construct the LLM service for ``provider_id``, or ``None`` if unavailable."""
    try:
        return await _build_llm(provider_id, model, client)
    except Exception:
        logger.exception('Failed to build LLM service', extra={'provider': provider_id})
        return None


async def build_tts_service(
    provider_id: str,
    *,
    client: UboRPCClient,
) -> TTSService | None:
    """Construct the TTS service for ``provider_id``, or ``None`` if unavailable."""
    try:
        return await _build_tts(provider_id, client)
    except Exception:
        logger.exception('Failed to build TTS service', extra={'provider': provider_id})
        return None

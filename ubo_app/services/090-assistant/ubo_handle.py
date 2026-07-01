# ruff: noqa: D100, D103
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import ReducerRegistrar, register


async def setup(register_reducer: ReducerRegistrar) -> None:
    from reducer import reducer

    register_reducer(reducer)

    from setup import init_service

    await init_service()


def binary_env_provider() -> dict[str, str]:
    import os
    from pathlib import Path

    from ubo_app.constants import (
        MCP_GATEWAY_LISTEN_PORT,
        MCP_GATEWAY_TOKEN_SECRET_ID,
    )
    from ubo_app.constants.assistant import (
        ANTHROPIC_API_KEY_SECRET_ID,
        ASSEMBLYAI_API_KEY_SECRET_ID,
        CEREBRAS_API_KEY_SECRET_ID,
        DEEPGRAM_API_KEY_SECRET_ID,
        DEEPSEEK_API_KEY_SECRET_ID,
        DEFAULT_LLM_GENERIC_MODEL,
        DEFAULT_VENICE_IMAGE_MODEL,
        ELEVENLABS_API_KEY_SECRET_ID,
        ELEVENLABS_VOICE_ID,
        GENERIC_LLM_API_KEY_SECRET_ID,
        GENERIC_LLM_BASE_URL_SECRET_ID,
        GENERIC_LLM_MODEL_SECRET_ID,
        GOOGLE_API_KEY_SECRET_ID,
        GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
        GROK_API_KEY_SECRET_ID,
        MISTRAL_API_KEY_SECRET_ID,
        OLLAMA_ONPREM_URL_SECRET_ID,
        OPENAI_API_KEY_SECRET_ID,
        OPENROUTER_API_KEY_SECRET_ID,
        QWEN_API_KEY_SECRET_ID,
        RIME_API_KEY_SECRET_ID,
        VENICE_API_KEY_SECRET_ID,
    )

    return {
        'MCP_GATEWAY_TOKEN_SECRET_ID': MCP_GATEWAY_TOKEN_SECRET_ID,
        'MCP_GATEWAY_LISTEN_PORT': str(MCP_GATEWAY_LISTEN_PORT),
        'ASSEMBLYAI_API_KEY_SECRET_ID': ASSEMBLYAI_API_KEY_SECRET_ID,
        'UBO_ASSISTANT_LOG_LEVEL': os.environ.get(
            'UBO_ASSISTANT_LOG_LEVEL',
            'INFO',
        ),
        'UBO_ASSISTANT_LOG_PATH': os.environ.get(
            'UBO_ASSISTANT_LOG_PATH',
            str(Path.cwd() / 'ubo-assistant.log'),
        ),
        'UBO_ASSISTANT_WHISKER_ENABLED': os.environ.get(
            'UBO_ASSISTANT_WHISKER_ENABLED',
            '',
        ),
        'UBO_ASSISTANT_WHISKER_FILE': os.environ.get(
            'UBO_ASSISTANT_WHISKER_FILE',
            '',
        ),
        'GOOGLE_API_KEY_SECRET_ID': GOOGLE_API_KEY_SECRET_ID,
        'GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID': (
            GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID
        ),
        'OPENAI_API_KEY_SECRET_ID': OPENAI_API_KEY_SECRET_ID,
        'GROK_API_KEY_SECRET_ID': GROK_API_KEY_SECRET_ID,
        'CEREBRAS_API_KEY_SECRET_ID': CEREBRAS_API_KEY_SECRET_ID,
        'ANTHROPIC_API_KEY_SECRET_ID': ANTHROPIC_API_KEY_SECRET_ID,
        'QWEN_API_KEY_SECRET_ID': QWEN_API_KEY_SECRET_ID,
        'DEEPSEEK_API_KEY_SECRET_ID': DEEPSEEK_API_KEY_SECRET_ID,
        'OPENROUTER_API_KEY_SECRET_ID': OPENROUTER_API_KEY_SECRET_ID,
        'MISTRAL_API_KEY_SECRET_ID': MISTRAL_API_KEY_SECRET_ID,
        'VENICE_API_KEY_SECRET_ID': VENICE_API_KEY_SECRET_ID,
        'UBO_DEFAULT_ASSISTANT_VENICE_IMAGE_MODEL': DEFAULT_VENICE_IMAGE_MODEL,
        'GENERIC_LLM_BASE_URL_SECRET_ID': GENERIC_LLM_BASE_URL_SECRET_ID,
        'GENERIC_LLM_API_KEY_SECRET_ID': GENERIC_LLM_API_KEY_SECRET_ID,
        'GENERIC_LLM_MODEL_SECRET_ID': GENERIC_LLM_MODEL_SECRET_ID,
        'DEFAULT_LLM_GENERIC_MODEL': DEFAULT_LLM_GENERIC_MODEL,
        'OLLAMA_ONPREM_URL_SECRET_ID': OLLAMA_ONPREM_URL_SECRET_ID,
        'ELEVENLABS_API_KEY_SECRET_ID': ELEVENLABS_API_KEY_SECRET_ID,
        'ELEVENLABS_VOICE_ID': ELEVENLABS_VOICE_ID,
        'DEEPGRAM_API_KEY_SECRET_ID': DEEPGRAM_API_KEY_SECRET_ID,
        'RIME_API_KEY_SECRET_ID': RIME_API_KEY_SECRET_ID,
    }


register(
    service_id='assistant',
    label='Assistant',
    setup=setup,
    binary_path='bin/ubo-assistant',
    binary_env_provider=binary_env_provider,
)

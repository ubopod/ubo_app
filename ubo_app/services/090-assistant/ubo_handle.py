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
    from ubo_app.constants.assistant import (
        ASSEMBLYAI_API_KEY_SECRET_ID,
        CEREBRAS_API_KEY_SECRET_ID,
        DEEPGRAM_API_KEY_SECRET_ID,
        ELEVENLABS_API_KEY_SECRET_ID,
        ELEVENLABS_VOICE_ID,
        GOOGLE_API_KEY_SECRET_ID,
        GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
        GROK_API_KEY_SECRET_ID,
        OLLAMA_ONPREM_URL_SECRET_ID,
        OPENAI_API_KEY_SECRET_ID,
        RIME_API_KEY_SECRET_ID,
    )

    return {
        'ASSEMBLYAI_API_KEY_SECRET_ID': ASSEMBLYAI_API_KEY_SECRET_ID,
        'GOOGLE_API_KEY_SECRET_ID': GOOGLE_API_KEY_SECRET_ID,
        'GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID': (
            GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID
        ),
        'OPENAI_API_KEY_SECRET_ID': OPENAI_API_KEY_SECRET_ID,
        'GROK_API_KEY_SECRET_ID': GROK_API_KEY_SECRET_ID,
        'CEREBRAS_API_KEY_SECRET_ID': CEREBRAS_API_KEY_SECRET_ID,
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

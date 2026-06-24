"""Check each LLM provider answers a deterministic prompt via the one-shot path.

Send a fixed prompt with a known one-word answer to each LLM provider and assert
the expected answer comes back.

Validates each LLM provider + the one-shot pipeline. Marked ``providers``; each
provider is skipped when unconfigured. Local ``ollama`` (daemon) is deferred to
phase 2. ``ollama_onprem`` resolves its model at runtime (supply it via
``UBO_TEST_OLLAMA_ONPREM_MODEL``).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from provider_harness import LLM_PROVIDERS, run_pipeline
from ubo_bindings.ubo.v1 import AssistantPipelineStage

if TYPE_CHECKING:
    from provider_harness import FakeUboRPCClient, Provider
    from ubo_bindings.ubo.v1 import AssistantLlmName

_SYSTEM_PROMPT = 'You answer questions concisely.'
_PROMPT = 'What is the capital of France? Reply with only the city name.'
_EXPECTED = 'paris'


def _resolve_model(provider: Provider[AssistantLlmName]) -> str:
    if provider.id == 'ollama_onprem':
        return os.environ.get('UBO_TEST_OLLAMA_ONPREM_MODEL', '')
    return provider.model


@pytest.mark.providers
@pytest.mark.parametrize('provider', LLM_PROVIDERS, ids=lambda provider: provider.id)
async def test_llm(
    provider: Provider[AssistantLlmName],
    client: FakeUboRPCClient,
) -> None:
    """Prompt *provider* for a known one-word answer and assert it's returned."""
    if not provider.available():
        pytest.skip(f'LLM provider {provider.id!r} not configured')
    model = _resolve_model(provider)
    if not model:
        pytest.skip(f'{provider.id}: no test model configured')

    result = await run_pipeline(
        client,
        stages=[AssistantPipelineStage.LLM],
        text=_PROMPT,
        llm_provider=provider.enum,
        llm_model=model,
        system_prompt=_SYSTEM_PROMPT,
    )
    assert not result.errors, f'{provider.id} LLM errors: {result.errors}'
    assert _EXPECTED in result.text.lower(), (
        f'{provider.id} ({model}): expected {_EXPECTED!r} in response, got '
        f'{result.text!r}'
    )

"""Round-trip Piper-synthesized audio through each STT provider.

Synthesize a phrase once with Piper (local, deterministic), then transcribe it
with each STT provider and assert the words come through.

Validates each STT provider + the one-shot pipeline. Marked ``providers``; the
whole module is skipped if Piper (used to make the reference audio) isn't set up,
and each provider is skipped when unconfigured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from provider_harness import (
    PHRASE,
    STT_PROVIDERS,
    TTS_PROVIDERS,
    keyword_hit_ratio,
    resample_pcm,
    run_pipeline,
)
from ubo_bindings.ubo.v1 import AssistantPipelineStage, AssistantTtsName

if TYPE_CHECKING:
    from provider_harness import FakeUboRPCClient, Provider
    from ubo_bindings.ubo.v1 import AssistantSttName

_MIN_RATIO = 0.6
_PIPER = next(provider for provider in TTS_PROVIDERS if provider.id == 'piper')
_reference: dict[str, bytes] = {}


async def _reference_audio_16k(client: FakeUboRPCClient) -> bytes:
    """Piper-synthesized PHRASE at 16 kHz, generated once and cached."""
    if 'pcm' not in _reference:
        tts = await run_pipeline(
            client,
            stages=[AssistantPipelineStage.TTS],
            text=PHRASE,
            tts_provider=AssistantTtsName.PIPER,
        )
        assert not tts.errors, f'piper reference TTS errors: {tts.errors}'
        assert tts.audio, 'piper produced no reference audio'
        _reference['pcm'] = await resample_pcm(tts.audio, tts.rate or 48000, 16000)
    return _reference['pcm']


@pytest.mark.providers
@pytest.mark.parametrize('provider', STT_PROVIDERS, ids=lambda provider: provider.id)
async def test_stt_roundtrip(
    provider: Provider[AssistantSttName],
    client: FakeUboRPCClient,
) -> None:
    """Transcribe the Piper reference audio with *provider*, assert words."""
    if not _PIPER.available():
        pytest.skip('Piper (needed to synthesize the reference audio) is not set up')
    if not provider.available():
        pytest.skip(f'STT provider {provider.id!r} not configured')

    audio_16k = await _reference_audio_16k(client)
    stt = await run_pipeline(
        client,
        stages=[AssistantPipelineStage.STT],
        audio=audio_16k,
        sample_rate=16000,
        stt_provider=provider.enum,
    )
    assert not stt.errors, f'{provider.id} STT errors: {stt.errors}'

    ratio = keyword_hit_ratio(stt.text, PHRASE)
    assert ratio >= _MIN_RATIO, (
        f'{provider.id}: transcript {stt.text!r} matched only {ratio:.0%} of the '
        f'phrase words'
    )

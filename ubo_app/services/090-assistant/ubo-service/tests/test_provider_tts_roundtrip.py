"""Round-trip each TTS provider through Vosk to prove it produces real speech.

Synthesize a phrase with each TTS provider, transcribe the audio with Vosk, and
assert the original words come through.

Validates that each TTS provider + the one-shot pipeline produce real, decodable
speech. Marked ``providers`` (real APIs, network/cost); skipped per-provider when
unconfigured, and entirely when the Vosk model needed for the STT side is absent.
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
from ubo_bindings.ubo.v1 import AssistantPipelineStage, AssistantSttName

from ubo_assistant.vosk import DEFAULT_VOSK_MODEL_ID

if TYPE_CHECKING:
    from provider_harness import FakeUboRPCClient, Provider
    from ubo_bindings.ubo.v1 import AssistantTtsName

# TTS+STT is lossy; require a majority of the phrase's words to survive.
_MIN_RATIO = 0.6
_VOSK = next(provider for provider in STT_PROVIDERS if provider.id == 'vosk')


@pytest.mark.providers
@pytest.mark.parametrize('provider', TTS_PROVIDERS, ids=lambda provider: provider.id)
async def test_tts_roundtrip(
    provider: Provider[AssistantTtsName],
    client: FakeUboRPCClient,
) -> None:
    """Synthesize PHRASE with *provider*, transcribe via Vosk, assert words."""
    if not _VOSK.available():
        pytest.skip('Vosk model (needed to transcribe the TTS output) is not present')
    if not provider.available():
        pytest.skip(f'TTS provider {provider.id!r} not configured')

    tts = await run_pipeline(
        client,
        stages=[AssistantPipelineStage.TTS],
        text=PHRASE,
        tts_provider=provider.enum,
    )
    assert not tts.errors, f'{provider.id} TTS errors: {tts.errors}'
    assert tts.audio, f'{provider.id} produced no audio'

    audio_16k = await resample_pcm(tts.audio, tts.rate or 48000, 16000)
    stt = await run_pipeline(
        client,
        stages=[AssistantPipelineStage.STT],
        audio=audio_16k,
        sample_rate=16000,
        stt_provider=AssistantSttName.VOSK,
        vosk_model_id=DEFAULT_VOSK_MODEL_ID,
    )
    assert not stt.errors, f'{provider.id}->vosk STT errors: {stt.errors}'

    ratio = keyword_hit_ratio(stt.text, PHRASE)
    assert ratio >= _MIN_RATIO, (
        f'{provider.id}: transcript {stt.text!r} matched only {ratio:.0%} of the '
        f'phrase words'
    )

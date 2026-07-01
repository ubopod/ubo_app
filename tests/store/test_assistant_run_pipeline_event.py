"""Store boundary: assistant actions resolve into ``AssistantRunPipelineEvent``.

Dispatches the four actions that drive the assistant pipeline through the reducer
and asserts the emitted ``AssistantRunPipelineEvent`` resolves stages, providers,
model and per-engine selections from state. This is the core→event contract the
subprocess one-shot pipeline (validated by ``ubo-service/tests``) and the gRPC
round-trip rely on.

Uses the same ``importlib`` discipline as ``test_assistant_piper_voice.py``: the
reducer + classes are pulled from a freshly reloaded namespace so the suite
survives the ``sys.modules`` wipe integration tests perform.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction

    from ubo_app.store.services.assistant import (
        AssistantRunPipelineEvent,
        AssistantState,
    )

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the assistant reducer plus the run-pipeline action/event symbols."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.store.services import assistant as assistant_module

    assistant_module = importlib.reload(assistant_module)

    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_run_pipeline',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(reducer=module.reducer, assistant=assistant_module)


def _initial_state(ns: SimpleNamespace) -> AssistantState:
    init_action = cast('type[BaseAction]', ns.reducer.__globals__['InitAction'])()
    return cast('AssistantState', ns.reducer(None, init_action))


def _run_pipeline_event(
    ns: SimpleNamespace,
    result: object,
) -> AssistantRunPipelineEvent:
    from redux import CompleteReducerResult

    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    event = next(
        event
        for event in result.events
        if isinstance(event, ns.assistant.AssistantRunPipelineEvent)
    )
    return cast('AssistantRunPipelineEvent', event)


def test_synthesize_resolves_selected_tts_and_voices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesize emits a TTS-only event resolving the selected TTS + voices."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(
        _initial_state(ns),
        selected_tts=a.AssistantTTSName.OPENAI,
        selected_piper_voice='en/en_US/kristin/medium/en_US-kristin-medium',
        selected_kokoro_voice='af_heart',
        selected_vosk_model='vosk-model-small-en-us-0.15',
        selected_voices={a.AssistantTTSName.OPENAI: 'shimmer'},
    )

    event = _run_pipeline_event(
        ns,
        ns.reducer(
            state,
            a.AssistantSynthesizeAction(text='hello there', session_id='s1'),
        ),
    )

    assert event.stages == [a.AssistantPipelineStage.TTS]
    assert event.text == 'hello there'
    assert event.tts_provider == a.AssistantTTSName.OPENAI
    assert event.piper_voice_id == 'en/en_US/kristin/medium/en_US-kristin-medium'
    assert event.kokoro_voice_id == 'af_heart'
    assert event.vosk_model_id == 'vosk-model-small-en-us-0.15'
    assert event.tts_voice_id == 'shimmer'


def test_synthesize_falls_back_to_default_cloud_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no explicit selection, ``tts_voice_id`` resolves the provider default."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(
        _initial_state(ns),
        selected_tts=a.AssistantTTSName.RIME,
        selected_voices={},
    )

    event = _run_pipeline_event(
        ns,
        ns.reducer(
            state,
            a.AssistantSynthesizeAction(text='hi', session_id='s1b'),
        ),
    )

    assert event.tts_voice_id == a.DEFAULT_VOICES[a.AssistantTTSName.RIME]


def test_synthesize_explicit_provider_overrides_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ``tts_provider`` on the action wins over ``selected_tts``."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(_initial_state(ns), selected_tts=a.AssistantTTSName.OPENAI)

    event = _run_pipeline_event(
        ns,
        ns.reducer(
            state,
            a.AssistantSynthesizeAction(
                text='hi',
                session_id='s2',
                tts_provider=a.AssistantTTSName.VENICE,
            ),
        ),
    )

    assert event.tts_provider == a.AssistantTTSName.VENICE


def test_complete_resolves_llm_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Complete emits an LLM-only event resolving provider + per-provider model."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(
        _initial_state(ns),
        selected_llm=a.AssistantLLMName.ANTHROPIC,
        selected_models={a.AssistantLLMName.ANTHROPIC: 'claude-test-model'},
    )

    event = _run_pipeline_event(
        ns,
        ns.reducer(
            state,
            a.AssistantCompleteAction(text='what is 2+2?', session_id='s3'),
        ),
    )

    assert event.stages == [a.AssistantPipelineStage.LLM]
    assert event.text == 'what is 2+2?'
    assert event.llm_provider == a.AssistantLLMName.ANTHROPIC
    assert event.llm_model == 'claude-test-model'


def test_transcribe_resolves_stt_and_carries_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transcribe emits an STT-only event carrying the audio + selected STT."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(_initial_state(ns), selected_stt=a.AssistantSTTName.DEEPGRAM)

    event = _run_pipeline_event(
        ns,
        ns.reducer(
            state,
            a.AssistantTranscribeAction(
                audio=b'\x00\x01\x02\x03',
                session_id='s4',
                sample_rate=16000,
            ),
        ),
    )

    assert event.stages == [a.AssistantPipelineStage.STT]
    assert event.audio == b'\x00\x01\x02\x03'
    assert event.sample_rate == 16000
    assert event.stt_provider == a.AssistantSTTName.DEEPGRAM


def test_run_pipeline_passes_stages_and_providers_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RunPipeline forwards an arbitrary contiguous chain and explicit providers."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = _initial_state(ns)
    stages = [
        a.AssistantPipelineStage.STT,
        a.AssistantPipelineStage.LLM,
        a.AssistantPipelineStage.TTS,
    ]

    event = _run_pipeline_event(
        ns,
        ns.reducer(
            state,
            a.AssistantRunPipelineAction(
                session_id='s5',
                stages=stages,
                text='go',
                stt_provider=a.AssistantSTTName.VOSK,
                llm_provider=a.AssistantLLMName.OPENAI,
                tts_provider=a.AssistantTTSName.PIPER,
                llm_model='gpt-test',
            ),
        ),
    )

    assert event.stages == stages
    assert event.stt_provider == a.AssistantSTTName.VOSK
    assert event.llm_provider == a.AssistantLLMName.OPENAI
    assert event.tts_provider == a.AssistantTTSName.PIPER
    assert event.llm_model == 'gpt-test'

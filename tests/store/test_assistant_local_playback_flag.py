"""One-shot synthesis can return audio without speaking it on the device.

Synthesis is normally requested in order to be heard (the screen reader, voice
previews), so playback stays on by default. A caller that only wants the stream
back — the Wyoming TTS engine hands it to Home Assistant, which plays it on
whichever satellite asked — turns it off; otherwise the response is heard twice.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pytest
    from redux import CompleteReducerResult

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the assistant reducer alongside its store types."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    assistant = importlib.reload(
        importlib.import_module('ubo_app.store.services.assistant'),
    )
    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_playback',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(assistant=assistant, reducer=module.reducer)


def _run_event(ns: SimpleNamespace, action: object) -> object:
    """Run *action* through the reducer and return its run-pipeline event."""
    state = ns.assistant.AssistantState()
    result = cast('CompleteReducerResult', ns.reducer(state, action))
    events = [
        event
        for event in (result.events or [])
        if type(event).__name__ == 'AssistantRunPipelineEvent'
    ]
    assert len(events) == 1
    return events[0]


def test_synthesis_is_played_locally_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The screen reader and voice previews must keep speaking."""
    ns = _load(monkeypatch)

    event = _run_event(
        ns,
        ns.assistant.AssistantSynthesizeAction(text='hello', session_id='s1'),
    )

    assert getattr(event, 'play_locally', None) is True


def test_a_caller_can_ask_for_the_stream_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``play_locally=False`` reaches the service on the pipeline event."""
    ns = _load(monkeypatch)

    event = _run_event(
        ns,
        ns.assistant.AssistantSynthesizeAction(
            text='hello',
            session_id='s2',
            play_locally=False,
        ),
    )

    assert getattr(event, 'play_locally', None) is False


def test_the_general_pipeline_action_carries_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parametrized entry point exposes the same knob."""
    ns = _load(monkeypatch)

    event = _run_event(
        ns,
        ns.assistant.AssistantRunPipelineAction(
            session_id='s3',
            stages=[ns.assistant.AssistantPipelineStage.TTS],
            text='hello',
            play_locally=False,
        ),
    )

    assert getattr(event, 'play_locally', None) is False


def test_a_silent_session_skips_the_speaker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The policy the service consults reports silence for an opted-out session."""
    service_dir = SERVICE_PATH.as_posix()
    monkeypatch.syspath_prepend(service_dir)
    policy = importlib.reload(importlib.import_module('playback_policy'))

    policy.remember('quiet', play_locally=False)
    policy.remember('loud', play_locally=True)

    assert policy.should_play('loud', is_last_frame=False) is True
    assert policy.should_play('quiet', is_last_frame=False) is False
    # An unknown session plays: the default is to be heard.
    assert policy.should_play('never-seen', is_last_frame=False) is True


def test_a_silent_session_is_forgotten_after_its_last_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session ids must not accumulate for the life of the device."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    policy = importlib.reload(importlib.import_module('playback_policy'))

    policy.remember('quiet', play_locally=False)
    assert policy.should_play('quiet', is_last_frame=True) is False

    assert policy._silent_sessions == set()  # noqa: SLF001


def test_the_wyoming_tts_engine_opts_out() -> None:
    """The Wyoming TTS engine must not also speak its response on the device."""
    service_dir = (
        Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
    )
    source = (service_dir / 'engines.py').read_text()
    synthesize = source.split('AssistantSynthesizeAction(', 1)[1].split(')', 1)[0]

    assert 'play_locally=False' in synthesize

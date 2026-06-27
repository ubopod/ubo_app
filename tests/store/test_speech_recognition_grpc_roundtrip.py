"""gRPC-boundary serialization tests for the wake-word speech-recognition state.

Remote clients (web UI, mobile) receive the store state as protobuf and rebuild
it: ``rebuild_object(build_message(state))``. The wake-word model state therefore
has to survive that round-trip. This guards two shapes in particular:

- ``wake_word_models_status`` is a tuple of ``WakeWordModelStatusEntry`` records
  (not an enum-keyed dict, which the helpers can't round-trip — the keys are lost).
- ``wake_engines`` carries nested ``WakeWordTrigger`` records.

Assertions compare by ``.value``/string rather than object identity because
integration tests earlier in the full suite wipe ``sys.modules``, so the classes
``rebuild_object`` resolves via the registry can be a different generation than the
ones imported here (an ``is`` check across generations would spuriously fail).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ubo_app.rpc.message_to_object import rebuild_object
from ubo_app.rpc.object_to_message import build_message
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionState,
    WakeMode,
    WakeWordEngineConfig,
    WakeWordEngineName,
    WakeWordModelStatus,
    WakeWordModelStatusEntry,
    WakeWordTrigger,
)

if TYPE_CHECKING:
    import betterproto


def _roundtrip(state: SpeechRecognitionState) -> SpeechRecognitionState:
    message = cast('betterproto.Message', build_message(state))
    return cast('SpeechRecognitionState', rebuild_object(message))


def test_model_status_survives_roundtrip() -> None:
    """The per-engine model status tuple round-trips with engine + status intact."""
    state = SpeechRecognitionState(
        wake_engines=(),
        wake_word_models_status=(
            WakeWordModelStatusEntry(
                engine=WakeWordEngineName.OPENWAKEWORD,
                status=WakeWordModelStatus.AVAILABLE,
            ),
        ),
    )

    rebuilt = _roundtrip(state)

    statuses = {
        entry.engine.value: entry.status.value
        for entry in rebuilt.wake_word_models_status
    }
    assert statuses == {
        WakeWordEngineName.OPENWAKEWORD.value: WakeWordModelStatus.AVAILABLE.value,
    }


def test_wake_engine_triggers_survive_roundtrip() -> None:
    """Engine configs and their nested triggers round-trip field-for-field."""
    state = SpeechRecognitionState(
        wake_engines=(
            WakeWordEngineConfig(
                engine=WakeWordEngineName.OPENWAKEWORD,
                enabled=True,
                triggers=(
                    WakeWordTrigger(
                        id='hey_jarvis',
                        label='Hey Jarvis',
                        mode=WakeMode.CONVERSATION,
                        value='hey_jarvis_v0.1',
                        sensitivity=0.8,
                    ),
                ),
            ),
        ),
        wake_word_models_status=(),
    )

    rebuilt = _roundtrip(state)

    configs = {config.engine.value: config for config in rebuilt.wake_engines}
    oww = configs[WakeWordEngineName.OPENWAKEWORD.value]
    assert oww.enabled is True
    assert len(oww.triggers) == 1
    trigger = oww.triggers[0]
    assert trigger.id == 'hey_jarvis'
    assert trigger.label == 'Hey Jarvis'
    assert trigger.mode.value == WakeMode.CONVERSATION.value
    assert trigger.value == 'hey_jarvis_v0.1'
    assert trigger.sensitivity == 0.8


def test_empty_model_status_roundtrips_to_empty() -> None:
    """An empty status tuple stays empty (no phantom entries) after a round-trip."""
    state = SpeechRecognitionState(wake_engines=(), wake_word_models_status=())

    rebuilt = _roundtrip(state)

    assert tuple(rebuilt.wake_word_models_status) == ()

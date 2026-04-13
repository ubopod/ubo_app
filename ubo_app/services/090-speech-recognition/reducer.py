# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from redux import (
    BaseAction,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
)

from ubo_app.constants.assistant import ASSISTANT_WAKE_WORD, INTENTS_WAKE_WORD
from ubo_app.store.core.types import (
    MenuChooseByIndexAction,
    MenuGoBackAction,
    MenuGoHomeAction,
    MenuScrollAction,
    MenuScrollDirection,
    OpenRenderAction,
)
from ubo_app.store.services.assistant import (
    AssistantStartListeningAction,
)
from ubo_app.store.services.audio import (
    AudioChangeVolumeAction,
    AudioDevice,
)
from ubo_app.store.services.infrared import (
    InfraredSendCodeAction,
    InfraredSetShouldReceiveAction,
)
from ubo_app.store.services.rgb_ring import (
    RgbRingBlankAction,
    RgbRingCommandAction,
    RgbRingRainbowAction,
    RgbRingSequenceAction,
    RgbRingSetAllAction,
)
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionAction,
    SpeechRecognitionIntent,
    SpeechRecognitionReportIntentDetectionAction,
    SpeechRecognitionReportSpeechAction,
    SpeechRecognitionReportWakeWordDetectionAction,
    SpeechRecognitionSetIsAssistantActiveAction,
    SpeechRecognitionSetIsIntentsActiveAction,
    SpeechRecognitionSetSelectedEngineAction,
    SpeechRecognitionState,
    SpeechRecognitionStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redux import ReducerResult

    from ubo_app.store.main import UboAction


ACKNOWLEDGMENT_ACTION = RgbRingBlankAction()

# Registry mapping intent action_ids to their actions
_intent_actions: dict[str, list[UboAction]] = {}


def _register_intent(
    action_id: str,
    phrase: str | Sequence[str],
    action: UboAction | Sequence[UboAction],
) -> SpeechRecognitionIntent:
    """Register an intent action and return the intent with an action_id."""
    _intent_actions[action_id] = (
        list(action) if not isinstance(action, BaseAction) else [action]
    )
    return SpeechRecognitionIntent(phrase=phrase, action_id=action_id)


def reducer(
    state: SpeechRecognitionState | None,
    action: SpeechRecognitionAction,
) -> ReducerResult[SpeechRecognitionState, UboAction, None]:
    if state is None:
        if isinstance(action, InitAction):
            return SpeechRecognitionState(
                intents=[
                    _register_intent(
                        'speech:assistant-on',
                        'Turn on Assistant',
                        SpeechRecognitionSetIsAssistantActiveAction(is_active=True),
                    ),
                    _register_intent(
                        'speech:assistant-off',
                        'Turn off Assistant',
                        SpeechRecognitionSetIsAssistantActiveAction(is_active=False),
                    ),
                    _register_intent(
                        'speech:wifi-camera',
                        [
                            'Create WiFi Connection with Camera',
                            'Create WiFi Connection with QR Code',
                            'Create WiFi Connection using Camera',
                            'Create WiFi Connection using QR Code',
                        ],
                        OpenRenderAction(
                            kind='status',
                            title='Creating WiFi Connection',
                            props={
                                'icon': '󱛃',
                                'text': 'Creating Scanned WiFi Connection',
                                'icon_size': 56,
                                'text_font_size': 19,
                            },
                        ),
                    ),
                    _register_intent(
                        'speech:wifi-web',
                        [
                            'Create WiFi Connection with Web Dashboard',
                            'Create WiFi Connection with Web',
                            'Create WiFi Connection with Web UI',
                            'Create WiFi Connection using Web Dashboard',
                            'Create WiFi Connection using Web UI',
                            'Create WiFi Connection using Web',
                        ],
                        OpenRenderAction(
                            kind='status',
                            title='Creating WiFi Connection',
                            props={
                                'icon': '󱛃',
                                'text': 'Creating WiFi Connection via Web',
                                'icon_size': 56,
                                'text_font_size': 19,
                            },
                        ),
                    ),
                    _register_intent(
                        'speech:light-strip-toggle',
                        ['Turn on light strip', 'Turn off light strip'],
                        InfraredSendCodeAction(protocol='nec', scancode='0x40'),
                    ),
                    _register_intent(
                        'speech:lights-on',
                        'Turn on Lights',
                        RgbRingSetAllAction(color=(255, 255, 255)),
                    ),
                    _register_intent(
                        'speech:lights-off',
                        'Turn off Lights',
                        RgbRingSetAllAction(color=(0, 0, 0)),
                    ),
                    _register_intent(
                        'speech:lights-red',
                        'Turn Lights Red',
                        RgbRingSetAllAction(color=(255, 0, 0)),
                    ),
                    _register_intent(
                        'speech:lights-green',
                        'Turn Lights Green',
                        RgbRingSetAllAction(color=(0, 255, 0)),
                    ),
                    _register_intent(
                        'speech:lights-blue',
                        'Turn Lights Blue',
                        RgbRingSetAllAction(color=(0, 0, 255)),
                    ),
                    _register_intent(
                        'speech:lights-yellow',
                        'Turn Lights Yellow',
                        RgbRingSetAllAction(color=(255, 255, 0)),
                    ),
                    _register_intent(
                        'speech:lights-purple',
                        'Turn Lights Purple',
                        RgbRingSetAllAction(color=(255, 0, 255)),
                    ),
                    _register_intent(
                        'speech:lights-cyan',
                        'Turn Lights Cyan',
                        RgbRingSetAllAction(color=(0, 255, 255)),
                    ),
                    _register_intent(
                        'speech:lights-orange',
                        'Turn Lights Orange',
                        RgbRingSetAllAction(color=(255, 100, 0)),
                    ),
                    _register_intent(
                        'speech:lights-white',
                        'Turn Lights White',
                        RgbRingSetAllAction(color=(255, 255, 255)),
                    ),
                    _register_intent(
                        'speech:lights-rainbow',
                        'Turn Lights Rainbow',
                        RgbRingRainbowAction(rounds=0, wait=2500),
                    ),
                    _register_intent(
                        'speech:volume-up',
                        'Turn Volume Up',
                        AudioChangeVolumeAction(amount=0.1, device=AudioDevice.OUTPUT),
                    ),
                    _register_intent(
                        'speech:volume-down',
                        'Turn Volume Down',
                        AudioChangeVolumeAction(amount=-0.1, device=AudioDevice.OUTPUT),
                    ),
                    _register_intent(
                        'speech:button-one',
                        'Activate Button One',
                        MenuChooseByIndexAction(index=0),
                    ),
                    _register_intent(
                        'speech:button-two',
                        'Activate Button Two',
                        MenuChooseByIndexAction(index=1),
                    ),
                    _register_intent(
                        'speech:button-three',
                        'Activate Button Three',
                        MenuChooseByIndexAction(index=1),
                    ),
                    _register_intent(
                        'speech:go-back',
                        ['Activate Back Button', 'Go Back'],
                        MenuGoBackAction(),
                    ),
                    _register_intent(
                        'speech:go-home',
                        ['Activate Home Button', 'Go Home'],
                        MenuGoHomeAction(),
                    ),
                    _register_intent(
                        'speech:scroll-up',
                        ['Activate Up Button', 'Scroll Up'],
                        MenuScrollAction(direction=MenuScrollDirection.UP),
                    ),
                    _register_intent(
                        'speech:scroll-down',
                        ['Activate Down Button', 'Scroll Down'],
                        MenuScrollAction(direction=MenuScrollDirection.DOWN),
                    ),
                    _register_intent(
                        'speech:ir-receive-on',
                        [
                            'Enable Receive Keys',
                            'Turn on Receive Keys',
                            'Start Receiving IR',
                            'Enable IR Receiver',
                        ],
                        InfraredSetShouldReceiveAction(should_receive=True),
                    ),
                    _register_intent(
                        'speech:ir-receive-off',
                        [
                            'Disable Receive Keys',
                            'Turn off Receive Keys',
                            'Stop Receiving IR',
                            'Disable IR Receiver',
                        ],
                        InfraredSetShouldReceiveAction(should_receive=False),
                    ),
                ],
            )

        raise InitializationActionError(action)

    match action:
        case SpeechRecognitionSetSelectedEngineAction():
            return replace(
                state,
                selected_engine=action.engine_name,
                status=SpeechRecognitionStatus.IDLE,
            )

        case SpeechRecognitionSetIsIntentsActiveAction():
            return replace(
                state,
                is_intents_active=action.is_active,
                status=SpeechRecognitionStatus.IDLE
                if state.status is SpeechRecognitionStatus.INTENTS_WAITING
                else state.status,
            )

        case SpeechRecognitionSetIsAssistantActiveAction():
            return replace(
                state,
                is_assistant_active=action.is_active,
                status=SpeechRecognitionStatus.IDLE
                if state.status is SpeechRecognitionStatus.ASSISTANT_WAITING
                else state.status,
            )

        case SpeechRecognitionReportWakeWordDetectionAction(
            wake_word=wake_word,
        ):
            if (
                wake_word == INTENTS_WAKE_WORD
                and state.status is SpeechRecognitionStatus.IDLE
            ):
                new_status = (
                SpeechRecognitionStatus.INTENTS_WAITING
            )
                return CompleteReducerResult(
                    state=replace(state, status=new_status),
                    actions=[RgbRingSetAllAction(color=(0, 0, 255))],
                )
            if (
                wake_word == ASSISTANT_WAKE_WORD
                and state.status is SpeechRecognitionStatus.IDLE
            ):
                return CompleteReducerResult(
                    state=replace(state, status=SpeechRecognitionStatus.IDLE),
                    actions=[AssistantStartListeningAction()],
                )
            return CompleteReducerResult(
                state=replace(state, status=SpeechRecognitionStatus.IDLE),
                actions=[],
            )

        case SpeechRecognitionReportIntentDetectionAction():
            resolved = _intent_actions.get(action.intent.action_id)
            if resolved is None:
                return replace(state, status=SpeechRecognitionStatus.IDLE)
            rgb_ring_actions = [
                a for a in resolved if isinstance(a, RgbRingCommandAction)
            ]
            non_rgb_ring_actions = [
                a for a in resolved if not isinstance(a, RgbRingCommandAction)
            ]
            return CompleteReducerResult(
                state=replace(state, status=SpeechRecognitionStatus.IDLE),
                actions=[
                    RgbRingSequenceAction(
                        sequence=[ACKNOWLEDGMENT_ACTION, *rgb_ring_actions],
                    ),
                    *non_rgb_ring_actions,
                ],
            )

        case SpeechRecognitionReportSpeechAction():
            return CompleteReducerResult(
                state=replace(state, status=SpeechRecognitionStatus.IDLE),
                actions=[ACKNOWLEDGMENT_ACTION],
            )

        case _:
            return state

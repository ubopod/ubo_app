# ruff: noqa: D100, D103
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.constants import ASSISTANT_WAKE_WORD, INTENTS_WAKE_WORD
from ubo_app.store.core.types import (
    MenuChooseByIndexAction,
    MenuGoBackAction,
    MenuGoHomeAction,
    MenuScrollAction,
    MenuScrollDirection,
    OpenApplicationAction,
)
from ubo_app.store.input.types import InputMethod
from ubo_app.store.services.audio import (
    AudioChangeVolumeAction,
    AudioDevice,
    AudioSetMuteStatusAction,
)
from ubo_app.store.services.infrared import InfraredSendCodeAction
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
    from redux import ReducerResult

    from ubo_app.store.main import UboAction


ACKNOWLEDGMENT_ACTION = RgbRingBlankAction()


def reducer(
    state: SpeechRecognitionState | None,
    action: SpeechRecognitionAction,
) -> ReducerResult[SpeechRecognitionState, UboAction, None]:
    if state is None:
        if isinstance(action, InitAction):
            return SpeechRecognitionState(
                intents=[
                    SpeechRecognitionIntent(
                        phrase='Turn on Assistant',
                        action=SpeechRecognitionSetIsAssistantActiveAction(
                            is_active=True,
                        ),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn off Assistant',
                        action=SpeechRecognitionSetIsAssistantActiveAction(
                            is_active=False,
                        ),
                    ),
                    SpeechRecognitionIntent(
                        phrase=[
                            'Create WiFi Connection with Camera',
                            'Create WiFi Connection with QR Code',
                            'Create WiFi Connection using Camera',
                            'Create WiFi Connection using QR Code',
                        ],
                        action=OpenApplicationAction(
                            application_id='wifi:create-connection-page',
                            initialization_kwargs={
                                'input_methods': (InputMethod.CAMERA,),
                            },
                        ),
                    ),
                    SpeechRecognitionIntent(
                        phrase=[
                            'Create WiFi Connection with Web Dashboard',
                            'Create WiFi Connection with Web',
                            'Create WiFi Connection with Web UI',
                            'Create WiFi Connection using Web Dashboard',
                            'Create WiFi Connection using Web UI',
                            'Create WiFi Connection using Web',
                        ],
                        action=OpenApplicationAction(
                            application_id='wifi:create-connection-page',
                            initialization_kwargs={
                                'input_methods': (InputMethod.WEB_DASHBOARD,),
                            },
                        ),
                    ),
                    SpeechRecognitionIntent(
                        phrase=['Turn on light strip', 'Turn off light strip'],
                        action=InfraredSendCodeAction(
                            protocol='nec',
                            scancode='0x40',
                        ),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn on Lights',
                        action=RgbRingSetAllAction(color=(255, 255, 255)),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn off Lights',
                        action=RgbRingSetAllAction(color=(0, 0, 0)),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Lights Red',
                        action=RgbRingSetAllAction(color=(255, 0, 0)),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Lights Green',
                        action=RgbRingSetAllAction(color=(0, 255, 0)),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Lights Blue',
                        action=RgbRingSetAllAction(color=(0, 0, 255)),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Lights Yellow',
                        action=RgbRingSetAllAction(color=(255, 255, 0)),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Lights Purple',
                        action=RgbRingSetAllAction(color=(255, 0, 255)),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Lights Cyan',
                        action=RgbRingSetAllAction(color=(0, 255, 255)),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Lights Orange',
                        action=RgbRingSetAllAction(color=(255, 100, 0)),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Lights White',
                        action=RgbRingSetAllAction(color=(255, 255, 255)),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Lights Rainbow',
                        action=RgbRingRainbowAction(rounds=0, wait=2500),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Volume Up',
                        action=AudioChangeVolumeAction(
                            amount=0.1,
                            device=AudioDevice.OUTPUT,
                        ),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Turn Volume Down',
                        action=AudioChangeVolumeAction(
                            amount=-0.1,
                            device=AudioDevice.OUTPUT,
                        ),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Mute Volume',
                        action=AudioSetMuteStatusAction(
                            is_mute=True,
                            device=AudioDevice.OUTPUT,
                        ),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Unmute Volume',
                        action=AudioSetMuteStatusAction(
                            is_mute=False,
                            device=AudioDevice.OUTPUT,
                        ),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Activate Button One',
                        action=MenuChooseByIndexAction(index=0),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Activate Button Two',
                        action=MenuChooseByIndexAction(index=1),
                    ),
                    SpeechRecognitionIntent(
                        phrase='Activate Button Three',
                        action=MenuChooseByIndexAction(index=1),
                    ),
                    SpeechRecognitionIntent(
                        phrase=['Activate Back Button', 'Go Back'],
                        action=MenuGoBackAction(),
                    ),
                    SpeechRecognitionIntent(
                        phrase=['Activate Home Button', 'Go Home'],
                        action=MenuGoHomeAction(),
                    ),
                    SpeechRecognitionIntent(
                        phrase=['Activate Up Button', 'Scroll Up'],
                        action=MenuScrollAction(direction=MenuScrollDirection.UP),
                    ),
                    SpeechRecognitionIntent(
                        phrase=['Activate Down Button', 'Scroll Down'],
                        action=MenuScrollAction(direction=MenuScrollDirection.DOWN),
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
        ) if (
            wake_word in (INTENTS_WAKE_WORD, ASSISTANT_WAKE_WORD)
            and state.status is SpeechRecognitionStatus.IDLE
        ):
            new_status = (
                SpeechRecognitionStatus.INTENTS_WAITING
                if wake_word == INTENTS_WAKE_WORD
                else SpeechRecognitionStatus.ASSISTANT_WAITING
            )
            return CompleteReducerResult(
                state=replace(state, status=new_status),
                actions=[RgbRingRainbowAction(rounds=0, wait=800)],
            )

        case SpeechRecognitionReportIntentDetectionAction():
            actions = (
                action.intent.action
                if isinstance(action.intent.action, Sequence)
                else [action.intent.action]
            )
            rgb_ring_actions = [
                action for action in actions if isinstance(action, RgbRingCommandAction)
            ]
            non_rgb_ring_actions = [
                action
                for action in actions
                if not isinstance(action, RgbRingCommandAction)
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

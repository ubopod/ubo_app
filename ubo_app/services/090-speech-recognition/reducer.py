# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.constants import ASSISTANT_DEBUG_PATH, ASSISTANT_WAKE_WORD, WAKE_WORD
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
                            initialization_kwargs={'input_methods': InputMethod.CAMERA},
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
                                'input_methods': InputMethod.WEB_DASHBOARD,
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

    if isinstance(action, SpeechRecognitionSetIsIntentsActiveAction):
        return replace(state, is_intents_active=action.is_active)

    if isinstance(action, SpeechRecognitionSetIsAssistantActiveAction):
        return replace(state, is_assistant_active=action.is_active)

    if isinstance(action, SpeechRecognitionReportWakeWordDetectionAction):
        if action.wake_word == WAKE_WORD:
            return CompleteReducerResult(
                state=replace(state, status=SpeechRecognitionStatus.INTENTS_WAITING),
                actions=[RgbRingRainbowAction(rounds=0, wait=800)],
            )
        if action.wake_word == ASSISTANT_WAKE_WORD:
            return CompleteReducerResult(
                state=replace(state, status=SpeechRecognitionStatus.ASSISTANT_WAITING),
                actions=[RgbRingRainbowAction(rounds=0, wait=800)],
            )

    if isinstance(action, SpeechRecognitionReportIntentDetectionAction):
        actions = (
            action.intent.action
            if isinstance(action.intent.action, Sequence)
            else [action.intent.action]
        )
        rgb_ring_actions = [
            action for action in actions if isinstance(action, RgbRingCommandAction)
        ]
        non_rgb_ring_actions = [
            action for action in actions if not isinstance(action, RgbRingCommandAction)
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

    if isinstance(action, SpeechRecognitionReportSpeechAction):
        if ASSISTANT_DEBUG_PATH is not None:
            with Path(ASSISTANT_DEBUG_PATH).with_suffix('.wav').open('wb') as f:
                f.write(action.raw_audio)
            with Path(ASSISTANT_DEBUG_PATH).with_suffix('.txt').open('wb') as f:
                f.write(action.text.encode('utf-8'))
        return CompleteReducerResult(
            state=replace(state, status=SpeechRecognitionStatus.IDLE),
            actions=[ACKNOWLEDGMENT_ACTION],
        )
    return state

# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import TypeAlias

from redux import BaseAction, BaseEvent, Immutable

Color: TypeAlias = (
    tuple[float | int, float | int, float | int]
    | tuple[float | int, float | int, float | int, float | int]
)


class LedRingAction(BaseAction):
    ...


class LedRingEvent(BaseEvent):
    ...


class LedRingSetIsConnectedAction(LedRingAction):
    is_connected: bool | None = None


class LedRingSetIsBusyAction(LedRingAction):
    is_busy: bool | None = None


class LedRingCommandAction(LedRingAction):
    ...


class LedRingWaitableCommandAction(LedRingCommandAction):
    wait: int = 100


class LedRingColorfulCommandAction(LedRingCommandAction):
    color: Color = (255, 255, 255)


class LedRingSetEnabledAction(LedRingCommandAction):
    enabled: bool = True


class LedRingSetAllAction(LedRingColorfulCommandAction):
    ...


class LedRingSetBrightnessAction(LedRingCommandAction):
    brightness: float = 0.5


class LedRingBlankAction(LedRingCommandAction):
    ...


class LedRingRainbowAction(LedRingWaitableCommandAction):
    rounds: int


class LedRingProgressWheelStepAction(LedRingColorfulCommandAction):
    ...


class LedRingPulseAction(LedRingWaitableCommandAction, LedRingColorfulCommandAction):
    repetitions: int = 5


class LedRingBlinkAction(LedRingWaitableCommandAction, LedRingColorfulCommandAction):
    repetitions: int = 5


class LedRingSpinningWheelAction(
    LedRingWaitableCommandAction,
    LedRingColorfulCommandAction,
):
    length: int = 5
    repetitions: int = 5


class LedRingProgressWheelAction(LedRingColorfulCommandAction):
    percentage: float = 0.5


class LedRingFillUptoAction(LedRingWaitableCommandAction, LedRingColorfulCommandAction):
    percentage: float = 0.5


class LedRingFillDownfromAction(
    LedRingWaitableCommandAction,
    LedRingColorfulCommandAction,
):
    percentage: float = 0.5


class LedRingCommandEvent(LedRingEvent):
    command: str


class LedRingState(Immutable):
    is_connected: bool
    is_busy: bool

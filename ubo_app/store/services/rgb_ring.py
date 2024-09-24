# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from typing import TypeAlias

from immutable import Immutable
from redux import BaseAction, BaseEvent

RgbColorElement: TypeAlias = float | int
RgbColor: TypeAlias = (
    tuple[RgbColorElement, RgbColorElement, RgbColorElement]
    | tuple[RgbColorElement, RgbColorElement, RgbColorElement, RgbColorElement]
)


class RgbRingAction(BaseAction): ...


class RgbRingEvent(BaseEvent): ...


class RgbRingSetIsConnectedAction(RgbRingAction):
    is_connected: bool | None = None


class RgbRingSetIsBusyAction(RgbRingAction):
    is_busy: bool | None = None


class RgbRingCommandAction(RgbRingAction): ...


class RgbRingWaitableCommandAction(RgbRingCommandAction):
    wait: int = 100


class RgbRingColorfulCommandAction(RgbRingCommandAction):
    color: RgbColor = (255, 255, 255)


class RgbRingSetEnabledAction(RgbRingCommandAction):
    enabled: bool = True


class RgbRingSetAllAction(RgbRingColorfulCommandAction): ...


class RgbRingSetBrightnessAction(RgbRingCommandAction):
    brightness: float = 0.5


class RgbRingBlankAction(RgbRingCommandAction): ...


class RgbRingRainbowAction(RgbRingWaitableCommandAction):
    rounds: int


class RgbRingProgressWheelStepAction(RgbRingColorfulCommandAction): ...


class RgbRingPulseAction(RgbRingWaitableCommandAction, RgbRingColorfulCommandAction):
    repetitions: int = 5


class RgbRingBlinkAction(RgbRingWaitableCommandAction, RgbRingColorfulCommandAction):
    repetitions: int = 5


class RgbRingSpinningWheelAction(
    RgbRingWaitableCommandAction,
    RgbRingColorfulCommandAction,
):
    length: int = 5
    repetitions: int = 5


class RgbRingProgressWheelAction(RgbRingColorfulCommandAction):
    percentage: float = 0.5


class RgbRingFillUptoAction(RgbRingWaitableCommandAction, RgbRingColorfulCommandAction):
    percentage: float = 0.5


class RgbRingFillDownfromAction(
    RgbRingWaitableCommandAction,
    RgbRingColorfulCommandAction,
):
    percentage: float = 0.5


class RgbRingCommandEvent(RgbRingEvent):
    command: list[str]


class RgbRingState(Immutable):
    is_connected: bool
    is_busy: bool

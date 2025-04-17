# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
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


class RgbRingSetIsBusyAction(RgbRingAction):
    is_busy: bool | None = None


class RgbRingCommandAction(RgbRingAction):
    def as_command(self) -> str:
        return ''


class RgbRingWaitableCommandAction(RgbRingCommandAction):
    wait: int = 100

    def as_command(self) -> str:
        return f'{super().as_command()} {self.wait}'


class RgbRingColorfulCommandAction(RgbRingCommandAction):
    color: RgbColor = (255, 255, 255)

    def as_command(self) -> str:
        return f'{super().as_command()} {self.color[0]} {self.color[1]} {self.color[2]}'


class RgbRingSetEnabledAction(RgbRingCommandAction):
    enabled: bool = True

    def as_command(self) -> str:
        if self.enabled:
            return 'set_enabled'
        return 'set_disabled'


class RgbRingSetAllAction(RgbRingColorfulCommandAction):
    def as_command(self) -> str:
        return f'set_all{super().as_command()}'


class RgbRingSetBrightnessAction(RgbRingCommandAction):
    brightness: float = 0.5

    def as_command(self) -> str:
        if 0 <= self.brightness <= 1:
            return f'set_brightness {self.brightness}'
        msg = f'Invalid brightness value: {self.brightness}. Must be between 0 and 1.'
        raise ValueError(msg)


class RgbRingBlankAction(RgbRingCommandAction):
    def as_command(self) -> str:
        return 'blank'


class RgbRingRainbowAction(RgbRingWaitableCommandAction):
    wait: int = 1
    rounds: int

    def as_command(self) -> str:
        return f'rainbow {self.rounds}{super().as_command()}'


class RgbRingProgressWheelStepAction(RgbRingColorfulCommandAction):
    def as_command(self) -> str:
        return f'progress_wheel_step{super().as_command()}'


class RgbRingPulseAction(RgbRingWaitableCommandAction, RgbRingColorfulCommandAction):
    repetitions: int = 5

    def as_command(self) -> str:
        return f'pulse{super().as_command()} {self.repetitions}'


class RgbRingBlinkAction(RgbRingWaitableCommandAction, RgbRingColorfulCommandAction):
    repetitions: int = 5

    def as_command(self) -> str:
        return f'blink{super().as_command()} {self.repetitions}'


class RgbRingSpinningWheelAction(
    RgbRingWaitableCommandAction,
    RgbRingColorfulCommandAction,
):
    length: int = 5
    repetitions: int = 5

    def as_command(self) -> str:
        return f'spinning_wheel{super().as_command()} {self.length} {self.repetitions}'


class RgbRingProgressWheelAction(RgbRingColorfulCommandAction):
    percentage: float = 0.5

    def as_command(self) -> str:
        return f'progress_wheel{super().as_command()} {self.percentage}'


class RgbRingFillUptoAction(RgbRingWaitableCommandAction, RgbRingColorfulCommandAction):
    percentage: float = 0.5

    def as_command(self) -> str:
        return f'fill_upto{super().as_command()} {self.percentage}'


class RgbRingFillDownfromAction(
    RgbRingWaitableCommandAction,
    RgbRingColorfulCommandAction,
):
    percentage: float = 0.5

    def as_command(self) -> str:
        return f'fill_downfrom{super().as_command()} {self.percentage}'


class RgbRingSequenceAction(RgbRingCommandAction):
    sequence: list[RgbRingCommandAction]

    def as_command(self) -> str:
        return ' | '.join(command.as_command() for command in self.sequence)


class RgbRingCommandEvent(RgbRingEvent):
    command: list[str]


class RgbRingState(Immutable):
    is_busy: bool

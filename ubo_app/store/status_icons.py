# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from redux import BaseAction, InitializationActionError


@dataclass(frozen=True)
class IconState:
    symbol: str
    color: str
    priority: int


@dataclass(frozen=True)
class StatusIconsState:
    icons: list[IconState]


@dataclass(frozen=True)
class IconRegistrationActionPayload:
    icon: str
    color: str = 'white'
    priority: int = 0


@dataclass(frozen=True)
class IconRegistrationAction(BaseAction):
    payload: IconRegistrationActionPayload
    type: Literal['STATUS_ICONS_REGISTER'] = 'STATUS_ICONS_REGISTER'


IconAction = IconRegistrationAction


def reducer(state: StatusIconsState | None, action: IconAction) -> StatusIconsState:
    if state is None:
        if action.type == 'INIT':
            return StatusIconsState(icons=[])
        raise InitializationActionError
    if action.type == 'STATUS_ICONS_REGISTER':
        return replace(
            state,
            icons=sorted(
                [
                    *state.icons,
                    IconState(
                        symbol=action.payload.icon,
                        color=action.payload.color,
                        priority=action.payload.priority,
                    ),
                ],
                key=lambda entry: entry.priority,
            ),
        )
    return state

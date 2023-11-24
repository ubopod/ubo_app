# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace
from typing import Literal

from redux import BaseAction, Immutable, InitializationActionError


class IconState(Immutable):
    symbol: str
    color: str
    priority: int
    id: str | None


class StatusIconsState(Immutable):
    icons: list[IconState]


class IconRegistrationActionPayload(Immutable):
    icon: str
    color: str = 'white'
    priority: int = 0
    id: str | None = None


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
                    *[
                        icon_status
                        for icon_status in state.icons
                        if icon_status.id != action.payload.id or icon_status.id is None
                    ],
                    IconState(
                        symbol=action.payload.icon,
                        color=action.payload.color,
                        priority=action.payload.priority,
                        id=action.payload.id,
                    ),
                ],
                key=lambda entry: entry.priority,
            ),
        )
    return state

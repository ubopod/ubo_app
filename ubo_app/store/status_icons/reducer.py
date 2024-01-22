# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace

from redux import InitAction, InitializationActionError

from ubo_app.store.status_icons import (
    IconState,
    StatusIconsAction,
    StatusIconsRegisterAction,
    StatusIconsState,
)


def reducer(
    state: StatusIconsState | None,
    action: StatusIconsAction | InitAction,
) -> StatusIconsState:
    if state is None:
        if isinstance(action, InitAction):
            return StatusIconsState(icons=[])
        raise InitializationActionError(action)
    if isinstance(action, StatusIconsRegisterAction):
        return replace(
            state,
            icons=sorted(
                [
                    *[
                        icon_status
                        for icon_status in state.icons
                        if icon_status.id != action.id or icon_status.id is None
                    ],
                    IconState(
                        symbol=action.icon,
                        color=action.color,
                        priority=action.priority,
                        id=action.id,
                    ),
                ],
                key=lambda entry: entry.priority,
            ),
        )
    return state

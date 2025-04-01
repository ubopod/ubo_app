# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace

from redux import InitAction, InitializationActionError

from ubo_app.store.settings.types import SettingsServiceSetStatusAction
from ubo_app.store.status_icons.types import (
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
    if isinstance(action, StatusIconsRegisterAction) and action.service is not None:
        return replace(
            state,
            icons=sorted(
                [
                    *[
                        icon_state
                        for icon_state in state.icons
                        if icon_state.id != action.id or icon_state.id is None
                    ],
                    IconState(
                        symbol=action.icon,
                        color=action.color,
                        priority=action.priority,
                        service_id=action.service,
                        id=action.id,
                    ),
                ],
                key=lambda entry: entry.priority,
            ),
        )

    if isinstance(action, SettingsServiceSetStatusAction):  # noqa: SIM102
        if action.is_active is False:
            return replace(
                state,
                icons=[
                    icon_state
                    for icon_state in state.icons
                    if icon_state.service_id != action.service_id
                ],
            )

    return state

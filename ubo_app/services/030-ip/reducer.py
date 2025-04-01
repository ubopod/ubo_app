# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from constants import INTERNET_STATE_ICON_ID, INTERNET_STATE_ICON_PRIORITY
from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.colors import DANGER_COLOR
from ubo_app.store.services.ip import (
    IpSetIsConnectedAction,
    IpState,
    IpUpdateInterfacesAction,
)
from ubo_app.store.status_icons.types import StatusIconsRegisterAction

Action = InitAction | IpUpdateInterfacesAction


def reducer(
    state: IpState | None,
    action: Action,
) -> ReducerResult[IpState, StatusIconsRegisterAction, None]:
    if state is None:
        if isinstance(action, InitAction):
            return IpState(interfaces=[])
        raise InitializationActionError(action)

    if isinstance(action, IpUpdateInterfacesAction):
        return replace(state, interfaces=action.interfaces)

    if isinstance(action, IpSetIsConnectedAction):
        return CompleteReducerResult(
            state=replace(state, is_connected=action.is_connected),
            actions=[
                StatusIconsRegisterAction(
                    icon='󰖟'
                    if action.is_connected
                    else f'[color={DANGER_COLOR}]󰪎[/color]',
                    priority=INTERNET_STATE_ICON_PRIORITY,
                    id=INTERNET_STATE_ICON_ID,
                ),
            ],
        )

    return state

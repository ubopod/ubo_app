# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    InitAction,
    InitializationActionError,
)

from ubo_app.store.services.ip import (
    IpSetIsConnectedAction,
    IpState,
    IpUpdateInterfacesAction,
)

Action = InitAction | IpUpdateInterfacesAction


def reducer(
    state: IpState | None,
    action: Action,
) -> IpState:
    if state is None:
        if isinstance(action, InitAction):
            return IpState(interfaces=[])
        raise InitializationActionError(action)

    if isinstance(action, IpUpdateInterfacesAction):
        return replace(state, interfaces=action.interfaces)

    if isinstance(action, IpSetIsConnectedAction):
        return replace(state, is_connected=action.is_connected)

    return state

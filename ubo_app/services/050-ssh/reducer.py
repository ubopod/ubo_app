# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import InitAction, InitializationActionError

from ubo_app.store.services.ssh import (
    SSHAction,
    SSHClearEnabledStateAction,
    SSHState,
    SSHUpdateStateAction,
)


def reducer(
    state: SSHState | None,
    action: SSHAction | InitAction,
) -> SSHState:
    if state is None:
        if isinstance(action, InitAction):
            return SSHState(is_active=False, is_enabled=False)
        raise InitializationActionError(action)

    match action:
        case SSHClearEnabledStateAction():
            return replace(state, is_enabled=None)

        case SSHUpdateStateAction():
            if action.is_active is not None:
                state = replace(state, is_active=action.is_active)
            if action.is_enabled is not None:
                state = replace(state, is_enabled=action.is_enabled)
            return state

        case _:
            return state

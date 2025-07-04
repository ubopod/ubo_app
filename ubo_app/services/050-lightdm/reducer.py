# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import InitAction, InitializationActionError

from ubo_app.store.services.lightdm import (
    LightDMAction,
    LightDMClearEnabledStateAction,
    LightDMState,
    LightDMUpdateStateAction,
)


def reducer(
    state: LightDMState | None,
    action: LightDMAction | InitAction,
) -> LightDMState:
    if state is None:
        if isinstance(action, InitAction):
            return LightDMState()
        raise InitializationActionError(action)

    match action:
        case LightDMClearEnabledStateAction():
            return replace(state, is_enabled=None)

        case LightDMUpdateStateAction():
            if action.is_active is not None:
                state = replace(state, is_active=action.is_active)
            if action.is_enabled is not None:
                state = replace(state, is_enabled=action.is_enabled)
            if action.is_installed is not None:
                state = replace(state, is_installed=action.is_installed)
            if action.is_installing is not None:
                state = replace(state, is_installing=action.is_installing)
            return state

        case _:
            return state

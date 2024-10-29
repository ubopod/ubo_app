"""Reducer for the settings state."""

from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.settings.types import (
    SettingsAction,
    SettingsEvent,
    SettingsSetDebugModeEvent,
    SettingsState,
    SettingsToggleDebugModeAction,
)


def reducer(
    state: SettingsState | None,
    action: SettingsAction | InitAction,
) -> ReducerResult[SettingsState, None, SettingsEvent]:
    """Reducer for the settings state."""
    if state is None:
        if isinstance(action, InitAction):
            return SettingsState()

        raise InitializationActionError(action)

    if isinstance(action, SettingsToggleDebugModeAction):
        return CompleteReducerResult(
            state=replace(state, is_debug_enabled=not state.is_debug_enabled),
            events=[SettingsSetDebugModeEvent(is_enabled=not state.is_debug_enabled)],
        )

    return state

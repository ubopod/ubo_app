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
    SettingsReportServiceErrorAction,
    SettingsServiceSetStatusAction,
    SettingsSetDebugModeEvent,
    SettingsSetServicesAction,
    SettingsStartServiceAction,
    SettingsStartServiceEvent,
    SettingsState,
    SettingsStopServiceAction,
    SettingsStopServiceEvent,
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

    if isinstance(action, SettingsSetServicesAction):
        return CompleteReducerResult(
            state=replace(state, services=action.services),
            events=[
                SettingsStartServiceEvent(
                    service_id=service.id,
                    delay=index * action.gap_duration,
                )
                for index, service in enumerate(action.services.values())
            ],
        )

    if isinstance(action, SettingsStartServiceAction):
        return CompleteReducerResult(
            state=state,
            events=[SettingsStartServiceEvent(service_id=action.service_id)],
        )

    if isinstance(action, SettingsStopServiceAction):
        return CompleteReducerResult(
            state=state,
            events=[SettingsStopServiceEvent(service_id=action.service_id)],
        )

    if isinstance(action, SettingsServiceSetStatusAction):  # noqa: SIM102
        if state.services:
            return CompleteReducerResult(
                state=replace(
                    state,
                    services={
                        **state.services,
                        action.service_id: replace(
                            state.services[action.service_id],
                            is_active=action.is_active,
                        ),
                    },
                ),
            )

    if isinstance(action, SettingsReportServiceErrorAction):
        return replace(
            state,
            services={
                key: replace(value, errors=[*value.errors, action.error])
                if key == action.service_id
                else value
                for key, value in state.services.items()
            }
            if state.services
            else {},
        )

    return state

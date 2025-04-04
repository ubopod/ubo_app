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
    SettingsServiceSetIsEnabledAction,
    SettingsServiceSetLogLevelAction,
    SettingsServiceSetShouldRestartAction,
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
        enabled_services = [
            service for service in action.services.values() if service.is_enabled
        ]
        return CompleteReducerResult(
            state=replace(state, services=action.services),
            events=[
                SettingsStartServiceEvent(
                    service_id=service.id,
                    delay=index * action.gap_duration,
                )
                for index, service in enumerate(enabled_services)
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
            service = state.services.get(action.service_id)
            if service:
                events: list[SettingsEvent] = []
                if (
                    not action.is_active
                    and service.is_active
                    and service.should_auto_restart
                ):
                    events = [
                        SettingsStartServiceEvent(
                            service_id=action.service_id,
                            delay=2,
                        ),
                    ]
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
                    events=events,
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

    if isinstance(action, SettingsServiceSetIsEnabledAction):
        return replace(
            state,
            services={
                **state.services,
                action.service_id: replace(
                    state.services[action.service_id],
                    is_enabled=action.is_enabled,
                ),
            }
            if state.services
            else {},
        )

    if isinstance(action, SettingsServiceSetLogLevelAction):
        return replace(
            state,
            services={
                **state.services,
                action.service_id: replace(
                    state.services[action.service_id],
                    log_level=action.log_level,
                ),
            }
            if state.services
            else {},
        )

    if isinstance(action, SettingsServiceSetShouldRestartAction):
        return replace(
            state,
            services={
                **state.services,
                action.service_id: replace(
                    state.services[action.service_id],
                    should_auto_restart=action.should_auto_restart,
                ),
            }
            if state.services
            else {},
        )

    return state

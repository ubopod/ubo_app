"""Reducer for the settings state."""

from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)
from ubo_gui.constants import SUCCESS_COLOR

from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.settings.types import (
    ServicesStatus,
    SettingsAction,
    SettingsEvent,
    SettingsReportServiceErrorAction,
    SettingsServiceSetIsEnabledAction,
    SettingsServiceSetLogLevelAction,
    SettingsServiceSetShouldRestartAction,
    SettingsServiceSetStatusAction,
    SettingsSetServicesAction,
    SettingsStartServiceAction,
    SettingsStartServiceEvent,
    SettingsState,
    SettingsStopServiceAction,
    SettingsStopServiceEvent,
    SettingsToggleBetaVersionsAction,
    SettingsTogglePdbSignalAction,
    SettingsToggleVisualDebugAction,
)
from ubo_app.store.update_manager.types import UpdateManagerRequestCheckAction


def reducer(
    state: SettingsState | None,
    action: SettingsAction | InitAction,
) -> ReducerResult[
    SettingsState,
    UpdateManagerRequestCheckAction | NotificationsAddAction,
    SettingsEvent,
]:
    """Reducer for the settings state."""
    if state is None:
        if isinstance(action, InitAction):
            return SettingsState()

        raise InitializationActionError(action)

    if isinstance(action, SettingsTogglePdbSignalAction):
        return CompleteReducerResult(
            state=replace(
                state,
                pdb_signal=not state.pdb_signal,
            ),
            actions=[
                NotificationsAddAction(
                    notification=Notification(
                        title='PDB Debug',
                        content='Instructions',
                        extra_information=ReadableInformation(
                            text='First make sure ipdb is installed by running:\n\n'
                            '/opt/ubo/env/bin/pip install ipdb\n\n'
                            'You need to run it only once.\n'
                            'Then send a SIGUSR1 signal to the process:\n\n'
                            'kill -SIGUSR1 <PID>',
                            picovoice_text='',
                            piper_text='',
                        ),
                        icon='',
                        importance=Importance.MEDIUM,
                        color=SUCCESS_COLOR,
                        display_type=NotificationDisplayType.STICKY,
                    ),
                ),
            ]
            if not state.pdb_signal
            else [],
        )

    if isinstance(action, SettingsToggleVisualDebugAction):
        return replace(
            state,
            visual_debug=not state.visual_debug,
        )

    if isinstance(action, SettingsToggleBetaVersionsAction):
        return CompleteReducerResult(
            state=replace(
                state,
                beta_versions=not state.beta_versions,
            ),
            actions=[
                NotificationsAddAction(
                    notification=Notification(
                        title='Beta Versions',
                        content='Go to the About menu and select "Recent Versions" to '
                        'continue.',
                        icon='󰒓',
                        color=SUCCESS_COLOR,
                    ),
                ),
                UpdateManagerRequestCheckAction(),
            ]
            if not state.beta_versions
            else [],
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
                new_services = {
                    **state.services,
                    action.service_id: replace(
                        state.services[action.service_id],
                        is_active=action.is_active,
                    ),
                }
                all_services_active = all(
                    service.is_active for service in new_services.values()
                )
                return CompleteReducerResult(
                    state=replace(
                        state,
                        services=new_services,
                        services_status=ServicesStatus.READY
                        if all_services_active
                        else ServicesStatus.LOADING,
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

# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

import packaging.version
from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.colors import SECONDARY_COLOR
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAction,
    NotificationsAddAction,
)
from ubo_app.store.update_manager.types import (
    UPDATE_MANAGER_NOTIFICATION_ID,
    UpdateManagerAction,
    UpdateManagerCheckEvent,
    UpdateManagerEvent,
    UpdateManagerReportFailedCheckAction,
    UpdateManagerRequestCheckAction,
    UpdateManagerRequestUpdateAction,
    UpdateManagerSetVersionsAction,
    UpdateManagerState,
    UpdateManagerUpdateEvent,
    UpdateStatus,
)


def reducer(
    state: UpdateManagerState | None,
    action: UpdateManagerAction,
) -> ReducerResult[
    UpdateManagerState,
    NotificationsAction,
    UpdateManagerEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            return UpdateManagerState()
        raise InitializationActionError(action)

    match action:
        case UpdateManagerSetVersionsAction():
            state = replace(
                state,
                current_version=action.current_version,
                base_image_variant=action.base_image_variant,
                latest_version=action.latest_version,
                recent_versions=action.recent_versions,
            )
            latest_version = packaging.version.parse(action.latest_version)
            current_version = packaging.version.parse(action.current_version)
            if latest_version > current_version:
                return CompleteReducerResult(
                    state=replace(
                        state,
                        update_status=UpdateStatus.OUTDATED,
                    ),
                    actions=[
                        NotificationsAddAction(
                            notification=Notification(
                                id=UPDATE_MANAGER_NOTIFICATION_ID,
                                title='Update available!',
                                content=f'Ubo v{action.latest_version} is available. '
                                'Go to the About menu to update.',
                                display_type=NotificationDisplayType.FLASH
                                if action.flash_notification
                                else NotificationDisplayType.BACKGROUND,
                                color=SECONDARY_COLOR,
                                icon='󰬬',
                                chime=Chime.DONE,
                            ),
                        ),
                    ],
                )
            return replace(state, update_status=UpdateStatus.UP_TO_DATE)

        case UpdateManagerRequestCheckAction():
            return CompleteReducerResult(
                state=replace(state, update_status=UpdateStatus.CHECKING),
                events=[UpdateManagerCheckEvent()],
            )

        case UpdateManagerReportFailedCheckAction():
            return CompleteReducerResult(
                state=replace(state, update_status=UpdateStatus.FAILED_TO_CHECK),
            )

        case UpdateManagerRequestUpdateAction():
            return CompleteReducerResult(
                state=replace(state, update_status=UpdateStatus.UPDATING),
                events=[UpdateManagerUpdateEvent(version=action.version)],
            )

        case _:
            return state

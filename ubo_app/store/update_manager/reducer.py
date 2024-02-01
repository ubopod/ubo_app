# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace

import semver
from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)
from ubo_gui.constants import SECONDARY_COLOR

from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.update_manager import (
    UPDATE_MANAGER_NOTIFICATION_ID,
    UpdateManagerAction,
    UpdateManagerCheckEvent,
    UpdateManagerEvent,
    UpdateManagerSetStatusAction,
    UpdateManagerSetVersionsAction,
    UpdateManagerState,
    UpdateManagerUpdateEvent,
    UpdateStatus,
)

ABOUT_MENU_PATH = ['Dashboard', 'Main', 'About']


def reducer(
    state: UpdateManagerState | None,
    action: UpdateManagerAction,
) -> ReducerResult[
    UpdateManagerState,
    UpdateManagerSetStatusAction | NotificationsAddAction,
    UpdateManagerEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            return UpdateManagerState()
        raise InitializationActionError(action)

    if isinstance(action, UpdateManagerSetVersionsAction):
        state = replace(
            state,
            current_version=action.current_version,
            latest_version=action.latest_version,
        )
        if semver.compare(action.latest_version, action.current_version) == 1:
            return CompleteReducerResult(
                state=state,
                actions=[
                    UpdateManagerSetStatusAction(status=UpdateStatus.OUTDATED),
                    NotificationsAddAction(
                        notification=Notification(
                            id=UPDATE_MANAGER_NOTIFICATION_ID,
                            title='Update available!',
                            content=f"""Ubo v{action.latest_version
                            } is available. Go to the About menu to update.""",
                            display_type=NotificationDisplayType.FLASH
                            if action.flash_notification
                            else NotificationDisplayType.BACKGROUND,
                            color=SECONDARY_COLOR,
                            icon='system_update',
                            chime=Chime.DONE,
                        ),
                    ),
                ],
            )
        return CompleteReducerResult(
            state=state,
            actions=[UpdateManagerSetStatusAction(status=UpdateStatus.UP_TO_DATE)],
        )

    if isinstance(action, UpdateManagerSetStatusAction):
        events = []
        if action.status == UpdateStatus.CHECKING:
            events.append(UpdateManagerCheckEvent())
        elif action.status == UpdateStatus.UPDATING:
            events.append(UpdateManagerUpdateEvent())

        return CompleteReducerResult(
            state=replace(
                state,
                update_status=action.status,
            ),
            events=events,
        )

    return state

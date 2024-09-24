# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import contextlib
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
    NotificationsAction,
    NotificationsAddAction,
)
from ubo_app.store.update_manager import (
    UPDATE_MANAGER_NOTIFICATION_ID,
    UpdateManagerAction,
    UpdateManagerCheckEvent,
    UpdateManagerEvent,
    UpdateManagerSetStatusAction,
    UpdateManagerSetUpdateServiceStatusAction,
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
    UpdateManagerSetStatusAction | NotificationsAction,
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
            base_image_variant=action.base_image_variant,
            latest_version=action.latest_version,
            serial_number=action.serial_number,
        )
        version_comparison = 1
        with contextlib.suppress(ValueError):
            latest_version = semver.Version.parse(
                action.latest_version,
                optional_minor_and_patch=True,
            )
            current_version = semver.Version.parse(
                action.current_version,
                optional_minor_and_patch=True,
            )
            version_comparison = latest_version.compare(current_version)
        if version_comparison > 0 and not state.is_update_service_active:
            return CompleteReducerResult(
                state=state,
                actions=[
                    UpdateManagerSetStatusAction(status=UpdateStatus.OUTDATED),
                    NotificationsAddAction(
                        notification=Notification(
                            id=UPDATE_MANAGER_NOTIFICATION_ID,
                            title='Update available!',
                            content=f"""Ubo v{action.latest_version} is available. Go to
the About menu to update.""",
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

    if isinstance(action, UpdateManagerSetUpdateServiceStatusAction):
        return replace(state, is_update_service_active=action.is_active)

    return state

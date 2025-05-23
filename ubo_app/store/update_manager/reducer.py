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

    if isinstance(action, UpdateManagerSetVersionsAction):
        state = replace(
            state,
            current_version=action.current_version,
            base_image_variant=action.base_image_variant,
            latest_version=action.latest_version,
            recent_versions=action.recent_versions,
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
        if version_comparison > 0:
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
        return replace(state, update_status=UpdateStatus.UP_TO_DATE)

    if isinstance(action, UpdateManagerRequestCheckAction):
        return CompleteReducerResult(
            state=replace(state, update_status=UpdateStatus.CHECKING),
            events=[UpdateManagerCheckEvent()],
        )

    if isinstance(action, UpdateManagerReportFailedCheckAction):
        return CompleteReducerResult(
            state=replace(state, update_status=UpdateStatus.FAILED_TO_CHECK),
        )

    if isinstance(action, UpdateManagerRequestUpdateAction):
        return CompleteReducerResult(
            state=replace(state, update_status=UpdateStatus.UPDATING),
            events=[UpdateManagerUpdateEvent(version=action.version)],
        )

    return state

"""Reducer tests for the update-manager slice.

The reducer parses semantic versions, decides whether the device is outdated,
and turns check/update requests into their events.
"""

from __future__ import annotations

import pytest
from redux import InitAction, InitializationActionError

from ubo_app.store.services.notifications import (
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.update_manager.reducer import reducer
from ubo_app.store.update_manager.types import (
    UpdateManagerCheckEvent,
    UpdateManagerReportFailedCheckAction,
    UpdateManagerRequestCheckAction,
    UpdateManagerRequestUpdateAction,
    UpdateManagerSetVersionsAction,
    UpdateManagerState,
    UpdateManagerUpdateEvent,
    UpdateStatus,
)


def _set_versions(
    current: str,
    latest: str,
    *,
    flash: bool,
) -> UpdateManagerSetVersionsAction:
    return UpdateManagerSetVersionsAction(
        flash_notification=flash,
        current_version=current,
        base_image_variant='default',
        latest_version=latest,
    )


def test_none_state_init_and_raise() -> None:
    """InitAction builds state; any other action against None raises."""
    assert isinstance(reducer(None, InitAction()), UpdateManagerState)
    with pytest.raises(InitializationActionError):
        reducer(None, UpdateManagerRequestCheckAction())


def test_newer_latest_marks_outdated_and_flashes() -> None:
    """A newer available version marks OUTDATED and flashes when asked."""
    result = reducer(
        UpdateManagerState(),
        _set_versions('1.0.0', '2.0.0', flash=True),
    )

    assert result.state.update_status == UpdateStatus.OUTDATED
    notifications = [
        action
        for action in (result.actions or [])
        if isinstance(action, NotificationsAddAction)
    ]
    assert len(notifications) == 1
    assert (
        notifications[0].notification.display_type == NotificationDisplayType.FLASH
    )


def test_outdated_uses_background_notification_when_not_flashing() -> None:
    """Without the flash flag the update notice is a background progress item."""
    result = reducer(
        UpdateManagerState(),
        _set_versions('1.0.0', '2.0.0', flash=False),
    )

    notifications = [
        action
        for action in (result.actions or [])
        if isinstance(action, NotificationsAddAction)
    ]
    assert (
        notifications[0].notification.display_type
        == NotificationDisplayType.BACKGROUND
    )


def test_equal_versions_are_up_to_date_without_notification() -> None:
    """When latest equals current the device is up to date and stays quiet."""
    result = reducer(
        UpdateManagerState(),
        _set_versions('2.0.0', '2.0.0', flash=True),
    )

    assert result.update_status == UpdateStatus.UP_TO_DATE


def test_request_check_transitions_and_emits_event() -> None:
    """A check request enters CHECKING and emits the check event."""
    result = reducer(UpdateManagerState(), UpdateManagerRequestCheckAction())

    assert result.state.update_status == UpdateStatus.CHECKING
    assert any(
        isinstance(event, UpdateManagerCheckEvent) for event in (result.events or [])
    )


def test_failed_check_records_failure() -> None:
    """A failed check records FAILED_TO_CHECK."""
    result = reducer(UpdateManagerState(), UpdateManagerReportFailedCheckAction())

    assert result.state.update_status == UpdateStatus.FAILED_TO_CHECK


def test_request_update_transitions_and_carries_version() -> None:
    """An update request enters UPDATING and emits the target version."""
    result = reducer(
        UpdateManagerState(),
        UpdateManagerRequestUpdateAction(version='3.1.4'),
    )

    assert result.state.update_status == UpdateStatus.UPDATING
    events = [
        event
        for event in (result.events or [])
        if isinstance(event, UpdateManagerUpdateEvent)
    ]
    assert events
    assert events[0].version == '3.1.4'


def test_unhandled_action_returns_state_unchanged() -> None:
    """An action matching no case leaves the state untouched."""
    state = UpdateManagerState()
    assert reducer(state, InitAction()) is state

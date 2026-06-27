"""Tests for the Settings "gRPC Access" toggle reducer behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from redux import CompleteReducerResult, InitAction

from ubo_app.store.services.notifications import NotificationsAddAction
from ubo_app.store.settings.reducer import reducer
from ubo_app.store.settings.types import (
    SettingsState,
    SettingsToggleGrpcRemoteAccessAction,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_persistent_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep SettingsState's persistent-store reads off the real file."""
    store_path = tmp_path / 'state.json'
    monkeypatch.setattr('ubo_app.constants.PERSISTENT_STORE_PATH', store_path)
    monkeypatch.setattr(
        'ubo_app.utils.persistent_store.PERSISTENT_STORE_PATH',
        store_path,
    )


def _warnings(result: CompleteReducerResult) -> list[NotificationsAddAction]:
    return [
        action
        for action in (result.actions or [])
        if isinstance(action, NotificationsAddAction)
    ]


def test_toggle_on_flips_flag_and_warns() -> None:
    """Enabling flips the flag and emits exactly one security warning."""
    initial = reducer(None, InitAction())
    assert isinstance(initial, SettingsState)
    assert initial.grpc_remote_access is False

    result = reducer(initial, SettingsToggleGrpcRemoteAccessAction())

    assert isinstance(result, CompleteReducerResult)
    assert result.state.grpc_remote_access is True
    warnings = _warnings(result)
    assert len(warnings) == 1
    assert warnings[0].notification.id == 'grpc-access-warning'


def test_toggle_off_flips_flag_without_warning() -> None:
    """Disabling flips the flag back and emits no notification."""
    initial = reducer(None, InitAction())
    assert isinstance(initial, SettingsState)
    enabled = reducer(initial, SettingsToggleGrpcRemoteAccessAction())
    assert isinstance(enabled, CompleteReducerResult)

    result = reducer(enabled.state, SettingsToggleGrpcRemoteAccessAction())

    assert isinstance(result, CompleteReducerResult)
    assert result.state.grpc_remote_access is False
    assert _warnings(result) == []

"""Tests for the Settings "gRPC Access" toggle reducer behavior."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from redux import InitAction

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


def test_toggle_on_flips_flag_without_notification() -> None:
    """Enabling flips the flag and emits no notification.

    The security warning is merged into the docker service's single "gRPC
    exposed" notification (fired when Envoy actually starts exposing the port),
    so the reducer just flips the flag.
    """
    initial = reducer(None, InitAction())
    assert isinstance(initial, SettingsState)
    assert initial.grpc_remote_access is False

    result = reducer(initial, SettingsToggleGrpcRemoteAccessAction())

    assert isinstance(result, SettingsState)
    assert result.grpc_remote_access is True


def test_toggle_off_flips_flag_back() -> None:
    """Disabling flips the flag back, also without any notification."""
    initial = reducer(None, InitAction())
    assert isinstance(initial, SettingsState)
    enabled = replace(initial, grpc_remote_access=True)

    result = reducer(enabled, SettingsToggleGrpcRemoteAccessAction())

    assert isinstance(result, SettingsState)
    assert result.grpc_remote_access is False

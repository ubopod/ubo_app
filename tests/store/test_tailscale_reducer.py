"""Tests for the Tailscale reducer.

Covers the install/download flags and the status → ``is_active`` derivation
(``is_active`` is true only when ``BackendState`` is ``Running``).

NOTE: The Tailscale service reducer lives in a non-package service directory,
so we add that directory to ``sys.path`` before importing it, then clean up all
newly loaded modules so integration/flow tests still initialize fresh state.
"""

from __future__ import annotations

import sys
from pathlib import Path

from redux import InitAction

from ubo_app.store.services.tailscale import (
    TailscaleDoneDownloadingAction,
    TailscaleSetPendingAction,
    TailscaleSetStatusAction,
    TailscaleStartDownloadingAction,
    TailscaleState,
)


def _import_reducer():  # noqa: ANN202
    modules_before = set(sys.modules)

    service_dir = str(
        Path(__file__).resolve().parents[2]
        / 'ubo_app'
        / 'services'
        / '050-tailscale',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # pyright: ignore[reportMissingImports]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return reducer


reducer = _import_reducer()


def _init_state() -> TailscaleState:
    state = reducer(None, InitAction())
    assert isinstance(state, TailscaleState)
    return state


def test_initial_state() -> None:
    """Initial state is unknown-installed, not downloading, not active."""
    state = _init_state()
    assert state.is_installed is None
    assert state.is_downloading is False
    assert state.is_active is False
    assert state.backend_state is None


def test_downloading_flag_toggles() -> None:
    """Start/Done downloading toggle the ``is_downloading`` flag."""
    state = _init_state()
    state = reducer(state, TailscaleStartDownloadingAction())
    assert state.is_downloading is True
    state = reducer(state, TailscaleDoneDownloadingAction())
    assert state.is_downloading is False


def test_status_running_is_active() -> None:
    """A ``Running`` backend marks the connection active."""
    state = _init_state()
    state = reducer(
        state,
        TailscaleSetStatusAction(is_installed=True, backend_state='Running'),
    )
    assert state.is_installed is True
    assert state.backend_state == 'Running'
    assert state.is_active is True


def test_status_needs_login_is_not_active() -> None:
    """A non-``Running`` backend (e.g. ``NeedsLogin``) is not active."""
    state = _init_state()
    state = reducer(
        state,
        TailscaleSetStatusAction(is_installed=True, backend_state='NeedsLogin'),
    )
    assert state.is_installed is True
    assert state.is_active is False


def test_set_pending_resets_status() -> None:
    """Setting pending clears the known status back to unknown."""
    state = _init_state()
    state = reducer(
        state,
        TailscaleSetStatusAction(is_installed=True, backend_state='Running'),
    )
    state = reducer(state, TailscaleSetPendingAction())
    assert state.is_installed is None
    assert state.backend_state is None
    assert state.is_active is False

# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import InitAction, InitializationActionError

from ubo_app.store.services.vscode import (
    VSCodeAction,
    VSCodeDoneDownloadingAction,
    VSCodeSetStatusAction,
    VSCodeStartDownloadingAction,
    VSCodeState,
)


def reducer(state: VSCodeState | None, action: VSCodeAction) -> VSCodeState:
    if state is None:
        if isinstance(action, InitAction):
            return VSCodeState()
        raise InitializationActionError(action)

    if isinstance(action, VSCodeStartDownloadingAction):
        return replace(state, is_downloading=True)

    if isinstance(action, VSCodeDoneDownloadingAction):
        return replace(state, is_downloading=False)

    if isinstance(action, VSCodeSetStatusAction):
        return replace(
            state,
            is_binary_installed=action.is_binary_installed,
            is_logged_in=action.is_logged_in,
            status=action.status,
            last_update_timestamp=action.timestamp,
        )

    return state

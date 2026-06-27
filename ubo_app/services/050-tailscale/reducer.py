# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import (
    InitAction,
    InitializationActionError,
)

from ubo_app.store.services.tailscale import (
    TailscaleAction,
    TailscaleDoneDownloadingAction,
    TailscaleSetPendingAction,
    TailscaleSetStatusAction,
    TailscaleStartDownloadingAction,
    TailscaleState,
)


def reducer(
    state: TailscaleState | None,
    action: TailscaleAction,
) -> TailscaleState:
    if state is None:
        if isinstance(action, InitAction):
            return TailscaleState()
        raise InitializationActionError(action)

    match action:
        case TailscaleStartDownloadingAction():
            return replace(state, is_downloading=True)

        case TailscaleDoneDownloadingAction():
            return replace(state, is_downloading=False)

        case TailscaleSetPendingAction():
            return replace(
                state,
                is_installed=None,
                backend_state=None,
                is_active=False,
            )

        case TailscaleSetStatusAction():
            return replace(
                state,
                is_installed=action.is_installed,
                backend_state=action.backend_state,
                is_active=action.backend_state == 'Running',
            )

        case _:
            return state

"""Reducer for the Wyoming service."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.services.wyoming import (
    WyomingAccessPolicy,
    WyomingAction,
    WyomingAddAccessPolicyAction,
    WyomingEvent,
    WyomingRemoveAccessPolicyAction,
    WyomingReportEnginesStatusAction,
    WyomingReportSatelliteStatusAction,
    WyomingSatelliteWakeAction,
    WyomingSatelliteWakeEvent,
    WyomingSetEnginesEnabledAction,
    WyomingSetSatelliteEnabledAction,
    WyomingSetZeroconfEnabledAction,
    WyomingState,
    normalize_access_policies,
)

if TYPE_CHECKING:
    from redux import ReducerResult


def reducer(
    state: WyomingState | None,
    action: WyomingAction | InitAction,
) -> ReducerResult[WyomingState, WyomingAction, WyomingEvent]:
    """Apply Wyoming settings and runtime reports without side effects."""
    if state is None:
        if isinstance(action, InitAction):
            return WyomingState()
        raise InitializationActionError(action)

    match action:
        case WyomingSetSatelliteEnabledAction(enabled=enabled):
            return replace(state, is_satellite_enabled=enabled)
        case WyomingSetEnginesEnabledAction(enabled=enabled):
            return replace(state, is_engines_enabled=enabled)
        case WyomingAddAccessPolicyAction(kind=kind, value=value):
            return replace(
                state,
                access_policies=normalize_access_policies(
                    [
                        *state.access_policies,
                        WyomingAccessPolicy(kind=kind, value=value),
                    ],
                ),
            )
        case WyomingRemoveAccessPolicyAction(kind=kind, value=value):
            return replace(
                state,
                access_policies=tuple(
                    policy
                    for policy in state.access_policies
                    if (policy.kind, policy.value) != (kind, value)
                ),
            )
        case WyomingSetZeroconfEnabledAction(enabled=enabled):
            return replace(state, is_zeroconf_enabled=enabled)
        case WyomingSatelliteWakeAction(phrase=phrase, detector=detector):
            # Status is reported by the connection once it actually starts a run;
            # a wake with no connected Home Assistant is a no-op in the runtime.
            return CompleteReducerResult(
                state=state,
                events=[
                    WyomingSatelliteWakeEvent(phrase=phrase, detector=detector),
                ],
            )
        case WyomingReportSatelliteStatusAction(status=status, client=client):
            return replace(state, satellite_status=status, satellite_client=client)
        case WyomingReportEnginesStatusAction(
            status=status,
            active_requests=active_requests,
        ):
            return replace(
                state,
                engines_status=status,
                active_engine_requests=max(active_requests, 0),
            )
        case _:
            return state

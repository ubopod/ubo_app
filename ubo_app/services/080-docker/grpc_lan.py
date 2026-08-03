"""Pure decision helpers for the event-driven gRPC-LAN exposure.

Exposing gRPC to the LAN is driven by two events, never by monitoring Envoy's
status:

  * the user toggling the gRPC-remote-access setting, and
  * the Envoy container starting.

These helpers hold the small, side-effect-free decisions those handlers make so
they can be unit-tested without the Docker service. The handlers themselves
(daemon I/O, notifications, restarts) live in ``setup.py``.
"""

from __future__ import annotations

import enum


class GrpcToggle(enum.Enum):
    """Classification of a ``grpc_remote_access`` observation."""

    NONE = enum.auto()
    ENABLE = enum.auto()
    DISABLE = enum.auto()


def classify_grpc_toggle(*, previous: bool | None, current: bool) -> GrpcToggle:
    """Classify a ``grpc_remote_access`` change into an actionable transition.

    ``previous is None`` is the initial (boot) observation — deliberately
    classified as ``NONE`` so the download prompt can never fire at boot; the
    prompt only follows a genuine off→on toggle by the user.
    """
    if previous is None or previous == current:
        return GrpcToggle.NONE
    return GrpcToggle.ENABLE if current else GrpcToggle.DISABLE


def should_prompt_envoy(*, envoy_running: bool) -> bool:
    """Whether enabling gRPC access should prompt to download+start Envoy.

    Nothing is exposed unless Envoy is actually running, so the prompt is shown
    exactly when it is not.
    """
    return not envoy_running


def should_announce_exposed(*, grpc_enabled: bool) -> bool:
    """Whether an Envoy ``start`` should announce that gRPC is now exposed."""
    return grpc_enabled

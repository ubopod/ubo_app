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


def should_start_envoy_at_boot(
    *,
    grpc_enabled: bool,
    envoy_running: bool,
    image_present: bool,
) -> bool:
    """Whether boot should start Envoy so gRPC access is actually reachable.

    gRPC access defaults to on, so a fresh pod has to bring Envoy up by itself —
    without it the setting exposes nothing and the mobile clients never see the
    device.

    ``image_present`` gates this deliberately: the shipped image has the Envoy
    tarball preloaded, so it starts, while an install without the image stays
    silent rather than pulling ~50MB over the network unprompted at boot.
    """
    return grpc_enabled and not envoy_running and image_present


def should_announce_exposed(*, grpc_enabled: bool, boot_start: bool) -> bool:
    """Whether an Envoy ``start`` should announce that gRPC is now exposed.

    The announcement is a sticky warning acknowledging something the user just
    did, so a boot-reconciled start stays silent — otherwise every reboot of a
    default-configured pod would post it again.
    """
    return grpc_enabled and not boot_start

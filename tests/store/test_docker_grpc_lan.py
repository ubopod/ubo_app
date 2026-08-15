"""Decision tests for the event-driven Envoy gRPC-LAN exposure.

Exposure is driven by two events — the ``grpc_remote_access`` toggle and the
Envoy container starting — never by monitoring Envoy's status. These tests pin
the small pure decisions those handlers make (the side-effecting handlers live
in ``setup.py``, an autorun-bearing module that can't be imported standalone),
using the file-path loader discipline of the sibling docker tests.
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


def _grpc_lan_module() -> ModuleType:
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)
    try:
        return import_module('grpc_lan')
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


@pytest.fixture
def grpc_lan() -> ModuleType:
    """Freshly load the docker service's ``grpc_lan`` decision module."""
    return _grpc_lan_module()


# --- Toggle classification: no action at boot, act only on real transitions ---


def test_boot_value_is_not_a_transition(grpc_lan: ModuleType) -> None:
    """The boot observation is never actionable (keeps the prompt off at boot)."""
    assert (
        grpc_lan.classify_grpc_toggle(previous=None, current=True)
        is grpc_lan.GrpcToggle.NONE
    )
    assert (
        grpc_lan.classify_grpc_toggle(previous=None, current=False)
        is grpc_lan.GrpcToggle.NONE
    )


def test_unchanged_value_is_not_a_transition(grpc_lan: ModuleType) -> None:
    """A re-emitted identical value does nothing."""
    assert (
        grpc_lan.classify_grpc_toggle(previous=True, current=True)
        is grpc_lan.GrpcToggle.NONE
    )
    assert (
        grpc_lan.classify_grpc_toggle(previous=False, current=False)
        is grpc_lan.GrpcToggle.NONE
    )


def test_off_to_on_is_enable(grpc_lan: ModuleType) -> None:
    """A genuine off→on toggle is the only thing that can prompt/expose."""
    assert (
        grpc_lan.classify_grpc_toggle(previous=False, current=True)
        is grpc_lan.GrpcToggle.ENABLE
    )


def test_on_to_off_is_disable(grpc_lan: ModuleType) -> None:
    """A genuine on→off toggle tears down exposure."""
    assert (
        grpc_lan.classify_grpc_toggle(previous=True, current=False)
        is grpc_lan.GrpcToggle.DISABLE
    )


# --- Enable handler: prompt only when Envoy isn't running --------------------


def test_prompt_when_envoy_not_running(grpc_lan: ModuleType) -> None:
    """Enabling with Envoy down prompts to download+start it (nothing exposed)."""
    assert grpc_lan.should_prompt_envoy(envoy_running=False) is True


def test_no_prompt_when_envoy_running(grpc_lan: ModuleType) -> None:
    """Enabling with Envoy up applies exposure instead of prompting."""
    assert grpc_lan.should_prompt_envoy(envoy_running=True) is False


# --- Start handler: announce exposure only while gRPC access is on ------------


def test_announce_on_start_when_enabled(grpc_lan: ModuleType) -> None:
    """An Envoy start while gRPC access is on announces reachability."""
    assert grpc_lan.should_announce_exposed(grpc_enabled=True, boot_start=False) is True


def test_silent_on_start_when_disabled(grpc_lan: ModuleType) -> None:
    """An Envoy start while gRPC access is off stays silent."""
    assert (
        grpc_lan.should_announce_exposed(grpc_enabled=False, boot_start=False) is False
    )


def test_silent_on_boot_reconciled_start(grpc_lan: ModuleType) -> None:
    """Boot starting Envoy itself stays silent — nothing was acknowledged.

    gRPC access is on by default, so announcing here would post the sticky
    warning on every single reboot.
    """
    assert grpc_lan.should_announce_exposed(grpc_enabled=True, boot_start=True) is False


# --- Boot reconciliation: start Envoy so the default-on setting means something


def test_boot_starts_envoy_when_enabled_and_image_present(
    grpc_lan: ModuleType,
) -> None:
    """A fresh pod with the bundled image brings Envoy up by itself."""
    assert (
        grpc_lan.should_start_envoy_at_boot(
            grpc_enabled=True,
            envoy_running=False,
            image_present=True,
        )
        is True
    )


def test_boot_leaves_running_envoy_alone(grpc_lan: ModuleType) -> None:
    """An already-running Envoy is not restarted at boot."""
    assert (
        grpc_lan.should_start_envoy_at_boot(
            grpc_enabled=True,
            envoy_running=True,
            image_present=True,
        )
        is False
    )


def test_boot_never_pulls_a_missing_image(grpc_lan: ModuleType) -> None:
    """Without the image locally, boot stays silent rather than pulling it."""
    assert (
        grpc_lan.should_start_envoy_at_boot(
            grpc_enabled=True,
            envoy_running=False,
            image_present=False,
        )
        is False
    )


def test_boot_does_nothing_when_access_is_off(grpc_lan: ModuleType) -> None:
    """A user who opted out keeps Envoy down at boot."""
    assert (
        grpc_lan.should_start_envoy_at_boot(
            grpc_enabled=False,
            envoy_running=False,
            image_present=True,
        )
        is False
    )

"""Fixtures for hardware-in-the-loop satellite audio tests.

These tests drive **real hardware against the running production core**: the
pod plays a sentence through its speakers, an ESP32 satellite hears it over the
air and streams it back, and the recording is scored against the reference.
They deliberately do *not* boot their own core with ``app_context`` — the point
is to measure the deployed system, including the assistant subprocess, Piper
and the real audio device.

Gated twice: ``IS_RPI`` (the acoustics only exist on the pod) and an explicit
``UBO_RUN_HIL=1`` opt-in, because a run takes tens of seconds and makes noise.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from ubo_bindings.store.v1 import StoreServiceStub

# The satellite prints this once at boot; see ubo_lvgl/esp32/main/client_app.c.
# Read rather than hardcoded so reflashing or swapping boards needs no edit.
_AUDIO_SOURCE_RE = re.compile(r'mic audio_source=(\S+)')

# Held long enough for the board to latch a reset (a zero-length pulse is
# silently ignored), then a window covering boot + Wi-Fi association.
_RESET_PULSE_SECONDS = 0.15
_BOOT_BANNER_TIMEOUT = 45

SATELLITE_PORT = os.environ.get('UBO_SATELLITE_PORT', '/dev/ttyACM0')
SATELLITE_BAUD = int(os.environ.get('UBO_SATELLITE_BAUD', '115200'))
GRPC_HOST = os.environ.get('UBO_GRPC_LISTEN_ADDRESS', '127.0.0.1')
GRPC_PORT = int(os.environ.get('UBO_GRPC_LISTEN_PORT', '50051'))


# Only the tests that actually touch hardware are gated. Note this hook is
# called with EVERY collected item in the session, not just this directory's —
# so it must filter by path, or it silently skips the entire test suite.
_HARDWARE_DIR = Path(__file__).parent
_PURE_MODULES = {'test_audio_metrics.py'}


def pytest_collection_modifyitems(
    config: pytest.Config,  # noqa: ARG001
    items: list[pytest.Item],
) -> None:
    """Skip hardware-dependent tests unless explicitly opted in on a pod."""
    if os.environ.get('UBO_RUN_HIL') == '1':
        return
    skip = pytest.mark.skip(
        reason='hardware-in-the-loop; set UBO_RUN_HIL=1 on a pod with a satellite',
    )
    for item in items:
        path = Path(str(item.fspath))
        if path.parent != _HARDWARE_DIR or path.name in _PURE_MODULES:
            continue
        item.add_marker(skip)


@pytest.fixture(autouse=True)
def _setup_script() -> None:
    """Override the repo-wide setup-script fixture to a no-op.

    ``tests/conftest.py`` has an autouse ``_setup_script`` that walks from the
    test's directory to the repo root running any ``setup.sh`` it finds. On a
    Raspberry Pi, ``tests/setup.sh`` DELETES EVERY WI-FI CONNECTION — a clean
    slate that ``tests/flows/test_wifi.py`` genuinely wants, but which is
    catastrophic here.

    These tests run against a pod over the network, with a satellite that
    reaches the core over Wi-Fi. Running that teardown drops the pod off the
    network mid-run: the test hangs, the SSH session dies, and the pod comes
    back with no stored credentials. Defining a fixture of the same name in
    this closer conftest shadows the parent's, so the script never runs.
    """


@dataclass
class Satellite:
    """Identity of the attached satellite device."""

    audio_source: str
    port: str


@pytest.fixture(scope='session')
def satellite() -> Generator[Satellite]:
    """Discover the satellite's audio_source tag from its serial console.

    Resets the board so the boot banner is guaranteed to appear: the
    USB-Serial-JTAG endpoint does not auto-reset when the port is opened, so
    simply reading can block forever on an already-booted device.
    """
    serial = pytest.importorskip('serial', reason='pyserial required for HIL tests')

    import time

    connection = serial.Serial(SATELLITE_PORT, SATELLITE_BAUD, timeout=1)
    try:
        # The RTS pulse must be held long enough for the board to latch the
        # reset; toggling high->low with no delay is too short to register and
        # the device just keeps running, so nothing is ever printed.
        connection.setDTR(False)
        connection.setRTS(True)
        time.sleep(_RESET_PULSE_SECONDS)
        connection.setRTS(False)

        deadline = time.time() + _BOOT_BANNER_TIMEOUT
        buffer = ''
        while time.time() < deadline:
            buffer += connection.read(4096).decode('utf-8', 'replace')
            match = _AUDIO_SOURCE_RE.search(buffer)
            if match:
                yield Satellite(audio_source=match.group(1), port=SATELLITE_PORT)
                return
        saw_boot = 'boot:' in buffer
        pytest.fail(
            f'satellite did not announce its audio_source within '
            f'{_BOOT_BANNER_TIMEOUT}s on {SATELLITE_PORT}. '
            + (
                'It did reboot, so the console works but the client never '
                'reached the point of announcing — check Wi-Fi association.'
                if saw_boot
                else 'No boot banner at all: the reset did not take, or the '
                'firmware was built WITH the PPP profile (PPP and the log '
                'console cannot share the USB endpoint).'
            )
            + f' Last 300 chars: {buffer[-300:]!r}',
        )
    finally:
        connection.close()


@pytest.fixture
async def rpc() -> AsyncGenerator[StoreServiceStub]:
    """GRPC channel to the running core, with a liveness probe first."""
    pytest.importorskip('grpclib', reason='grpclib required for HIL tests')
    from grpclib.client import Channel
    from ubo_bindings.store.v1 import StoreServiceStub as Stub

    channel = Channel(host=GRPC_HOST, port=GRPC_PORT)
    try:
        yield Stub(channel)
    finally:
        channel.close()

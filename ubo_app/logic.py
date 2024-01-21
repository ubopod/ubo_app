"""Application logic."""
from __future__ import annotations

import subprocess

from ubo_app.store import subscribe_event
from ubo_app.store.main import PowerOffEvent
from ubo_app.utils import initialize_board, turn_off_screen, turn_on_screen


def power_off(_: PowerOffEvent) -> None:
    """Power off the device."""
    turn_off_screen()

    subprocess.run(['/usr/bin/env', 'systemctl', 'poweroff', '-i'], check=True)  # noqa: S603


def setup() -> None:
    """Set up the application."""
    turn_on_screen()
    initialize_board()

    subscribe_event(PowerOffEvent, power_off)

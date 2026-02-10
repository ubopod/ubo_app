# ruff: noqa: D107
"""Device pairing page for the Zigbee service.

Shows pairing countdown and status during device pairing mode.
"""

from __future__ import annotations

import pathlib

from kivy.lang.builder import Builder
from kivy.properties import BooleanProperty, NumericProperty, StringProperty

from ubo_app.store.core.types import CloseApplicationAction
from ubo_app.store.main import store
from ubo_app.store.services.zigbee import ZigbeeStopPairingAction
from ubo_app.store.ubo_actions import register_application
from ubo_app.utils.gui import UboPageWidget


class DevicePairingPage(UboPageWidget):
    """Page shown during device pairing mode."""

    remaining_seconds: int = NumericProperty(60)
    is_pairing: bool = BooleanProperty(True)  # noqa: FBT003
    status_text: str = StringProperty('Waiting for device...')
    last_joined_device: str = StringProperty('')

    def __init__(self, duration: int = 60, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.remaining_seconds = duration
        self._setup_autorun()

    def _setup_autorun(self) -> None:
        """Set up autorun to track pairing state."""

        @store.autorun(
            lambda state: (
                state.zigbee.is_pairing,
                state.zigbee.pairing_remaining_seconds,
            ),
        )
        def update_pairing_state(
            data: tuple[bool, int],
        ) -> None:
            is_pairing, remaining = data
            self.is_pairing = is_pairing
            self.remaining_seconds = remaining

            if not is_pairing:
                self.status_text = 'Pairing complete'
            elif remaining > 0:
                self.status_text = f'Waiting for device... ({remaining}s)'
            else:
                self.status_text = 'Pairing ended'

        # Store reference to prevent garbage collection
        self._autorun = update_pairing_state

    def stop_pairing(self) -> None:
        """Stop pairing mode early."""
        store.dispatch(
            ZigbeeStopPairingAction(),
            CloseApplicationAction(application_instance_id=self.id),
        )


register_application(
    application=DevicePairingPage,
    application_id='zigbee:device-pairing',
)


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('device_pairing.kv')
    .resolve()
    .as_posix(),
)

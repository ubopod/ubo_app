# ruff: noqa: D100, D101, D102, D103, D104, D107, N999


from time import sleep

from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.led_ring import (
    LedRingBlinkAction,
    LedRingCommandEvent,
    LedRingSetBrightnessAction,
)


def init_service() -> None:
    from rgb_ring_client import RgbRingClient

    rgb_ring_client = RgbRingClient()

    def handle_led_ring_command(event: LedRingCommandEvent) -> None:
        rgb_ring_client.send(event.command)

    subscribe_event(LedRingCommandEvent, handle_led_ring_command)

    dispatch(LedRingSetBrightnessAction(brightness=0.2))
    dispatch(LedRingBlinkAction(repetitions=2))

# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from ubo_app.store.main import store
from ubo_app.store.services.rgb_ring import RgbRingCommandEvent, RgbRingPulseAction


def init_service() -> None:
    from rgb_ring_client import RgbRingClient

    rgb_ring_client = RgbRingClient()

    async def handle_rgb_ring_command(event: RgbRingCommandEvent) -> None:
        await rgb_ring_client.send(event.command)

    store.subscribe_event(RgbRingCommandEvent, handle_rgb_ring_command)

    store.dispatch(RgbRingPulseAction(repetitions=2, wait=180))

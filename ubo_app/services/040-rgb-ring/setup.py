# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from ubo_app.store.main import store
from ubo_app.store.services.rgb_ring import RgbRingCommandEvent, RgbRingPulseAction
from ubo_app.utils.eeprom import get_eeprom_data


def init_service() -> None:
    eeprom_data = get_eeprom_data()

    if (
        eeprom_data is None
        or 'led' not in eeprom_data
        or eeprom_data['led'] is None
        or eeprom_data['led']['model'] != 'neopixel'
    ):
        return

    from rgb_ring_client import RgbRingClient

    rgb_ring_client = RgbRingClient()

    async def handle_rgb_ring_command(event: RgbRingCommandEvent) -> None:
        await rgb_ring_client.send(event.command)

    store.subscribe_event(RgbRingCommandEvent, handle_rgb_ring_command)

    store.dispatch(RgbRingPulseAction(repetitions=2, wait=180))

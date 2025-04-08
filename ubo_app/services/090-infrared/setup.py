"""Initialize the infrared service."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, cast

from ubo_gui.menu.types import HeadlessMenu, Item, SubMenuItem

from ubo_app.logger import logger
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.dispatch_action import DispatchItem
from ubo_app.store.main import store
from ubo_app.store.services.infrared import (
    InfraredHandleReceivedCodeAction,
    InfraredSendCodeEvent,
    InfraredSetShouldPropagateAction,
    InfraredSetShouldReceiveAction,
)
from ubo_app.utils.async_ import to_thread
from ubo_app.utils.gui import SELECTED_ITEM_PARAMETERS, UNSELECTED_ITEM_PARAMETERS
from ubo_app.utils.persistent_store import register_persistent_store

EXPECTED_NEC_COMMAND_LENGTH = 4

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


def _reverse_bits(n: int, bit_size: int = 8) -> int:
    result = 0
    for _ in range(bit_size):
        result = (result << 1) | (n & 1)
        n >>= 1
    return result


@store.with_state(lambda state: state.infrared.should_receive_keypad_actions)
def _should_receive_keypad_actions(value: bool) -> bool:  # noqa: FBT001
    return value


def _monitor_ir(end_event: threading.Event) -> None:
    """Monitor infrared signals and decode them."""
    import adafruit_irremote
    import board
    import pulseio

    pulsein = pulseio.PulseIn(board.D24, maxlen=120, idle_state=True)
    try:
        decoder = adafruit_irremote.GenericDecode()
        while not end_event.is_set() and _should_receive_keypad_actions():
            pulses = decoder.read_pulses(cast('list', pulsein), blocking=False)
            if pulses:
                logger.verbose(
                    'Infrared: Heard pulses.',
                    extra={'length': len(pulses), 'pulses': pulses},
                )
                try:
                    code = tuple(decoder.decode_bits(pulses))
                    logger.debug(
                        'Infrared: Decoded code.',
                        extra={'code': code},
                    )
                    if len(code) == EXPECTED_NEC_COMMAND_LENGTH:
                        store.dispatch(
                            InfraredHandleReceivedCodeAction(code=code),
                        )
                except adafruit_irremote.IRNECRepeatException:
                    logger.verbose('Infrared: Received NEC repeat code.', exc_info=True)
                except adafruit_irremote.IRDecodeException:
                    logger.verbose(
                        'Infrared: Failed to decode infrared code.',
                        exc_info=True,
                    )

    finally:
        pulsein.deinit()


ir_ctl_lock = asyncio.Lock()
ir_commands_queue = asyncio.Queue()


async def _send_code(action: InfraredSendCodeEvent) -> None:
    await ir_commands_queue.put(action)
    async with ir_ctl_lock:
        action = await ir_commands_queue.get()
        logger.debug('Sending infrared code.', extra={'code': action.code})

        process = await asyncio.create_subprocess_exec(
            'ir-ctl',
            '-S',
            f'nec:0x{"".join(f"{_reverse_bits(x):02x}" for x in action.code)}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.wait(), timeout=1)
        if process.returncode is None:
            process.kill()
            msg = 'Infrared: Failed to send code, process killed due to timeout.'
            raise RuntimeError(msg)
        await asyncio.sleep(0.25)


def init_service() -> Subscriptions:
    """Initialize the infrared service."""
    end_event = threading.Event()

    # TODO(@sassanh): This is to avoid cpu load until we replace  # noqa: FIX002
    # adafruit ir receiver with an event driven library
    @store.autorun(lambda state: state.infrared.should_receive_keypad_actions)
    def run_monitor_ir(value: bool) -> None:  # noqa: FBT001
        if value:
            to_thread(_monitor_ir, end_event)

    register_persistent_store(
        'infrared_state:should_propagate_keypad_actions',
        lambda state: state.infrared.should_propagate_keypad_actions,
    )
    register_persistent_store(
        'infrared_state:should_receive_keypad_actions',
        lambda state: state.infrared.should_receive_keypad_actions,
    )

    @store.autorun(
        lambda state: (
            state.infrared.should_propagate_keypad_actions,
            state.infrared.should_receive_keypad_actions,
        ),
    )
    def menu_items(data: tuple[bool, bool]) -> list[Item]:
        should_propagate_keypad_actions, should_receive_keypad_actions = data
        return [
            DispatchItem(
                key='propagate_keys',
                label='Propagate Keys',
                store_action=InfraredSetShouldPropagateAction(
                    should_propagate=not should_propagate_keypad_actions,
                ),
                **(
                    SELECTED_ITEM_PARAMETERS
                    if should_propagate_keypad_actions
                    else UNSELECTED_ITEM_PARAMETERS
                ),
            ),
            DispatchItem(
                key='receive_keys',
                label='Receive Keys',
                store_action=InfraredSetShouldReceiveAction(
                    should_receive=not should_receive_keypad_actions,
                ),
                **(
                    SELECTED_ITEM_PARAMETERS
                    if should_receive_keypad_actions
                    else UNSELECTED_ITEM_PARAMETERS
                ),
            ),
        ]

    store.dispatch(
        RegisterSettingAppAction(
            key='infrared',
            category=SettingsCategory.HARDWARE,
            menu_item=SubMenuItem(
                label='Infrared',
                icon='󰻅',
                sub_menu=HeadlessMenu(
                    title='󰻅Infrared',
                    items=menu_items,
                ),
            ),
        ),
    )

    return [store.subscribe_event(InfraredSendCodeEvent, _send_code), end_event.set]

"""Initialize the infrared service."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ubo_gui.menu.types import HeadlessMenu, Item, SubMenuItem

from ubo_app.logger import logger
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.infrared import (
    InfraredHandleReceivedCodeAction,
    InfraredSendCodeEvent,
    InfraredSetShouldPropagateAction,
    InfraredSetShouldReceiveAction,
)
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import SELECTED_ITEM_PARAMETERS, UNSELECTED_ITEM_PARAMETERS
from ubo_app.utils.persistent_store import register_persistent_store
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


@store.with_state(lambda state: state.infrared.should_receive_keypad_actions)
def _should_receive_keypad_actions(value: bool) -> bool:  # noqa: FBT001
    return value


ir_ctl_lock = asyncio.Lock()
ir_commands_queue = asyncio.Queue()


async def _send_code(action: InfraredSendCodeEvent) -> None:
    await ir_commands_queue.put(action)
    async with ir_ctl_lock:
        action = await ir_commands_queue.get()
        logger.debug(
            'Sending infrared code.',
            extra={'protocol': action.protocol, 'scancode': action.scancode},
        )

        process = await asyncio.create_subprocess_exec(
            'ir-ctl',
            '-S',
            f'{action.protocol}:{action.scancode}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.wait(), timeout=1)
        if process.returncode is None:
            process.kill()
            msg = 'Infrared: Failed to send code, process killed due to timeout.'
            raise RuntimeError(msg)
        await asyncio.sleep(0.25)


async def _wait_for_ir_code() -> None:
    """Wait for IR codes from the system manager and dispatch them to the store."""
    while _should_receive_keypad_actions():
        try:
            async for response in await send_command(
                'infrared',
                'receive',
                has_output_stream=True,
            ):
                if response == 'nocode':
                    break
                protocol, scancode = response.split(':')
                logger.info(
                    'Received IR code from system manager',
                    extra={'protocol': protocol, 'scancode': scancode},
                )
                store.dispatch(
                    InfraredHandleReceivedCodeAction(
                        protocol=protocol,
                        scancode=scancode,
                    ),
                )
        except Exception:
            logger.exception('Failed to send infrared receive command')
            raise


def init_service() -> Subscriptions:
    """Initialize the infrared service."""
    ir_code_task: asyncio.Handle | None = None

    @store.autorun(lambda state: state.infrared.should_receive_keypad_actions)
    async def run_monitor_ir(value: bool) -> None:  # noqa: FBT001
        nonlocal ir_code_task
        if value:
            await send_command('infrared', 'start')
            ir_code_task = create_task(_wait_for_ir_code())
        else:
            await send_command('infrared', 'stop')
            if ir_code_task is not None:
                ir_code_task.cancel()

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
            UboDispatchItem(
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
            UboDispatchItem(
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

    return [
        store.subscribe_event(InfraredSendCodeEvent, _send_code),
    ]

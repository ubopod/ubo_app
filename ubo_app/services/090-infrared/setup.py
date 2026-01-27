"""Initialize the infrared service."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from ubo_gui.menu.types import HeadlessMenu, Item, SubMenuItem

from ubo_app.logger import logger
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.input.types import (
    InputCancelAction,
    InputFieldDescription,
    InputFieldType,
    SpeechInputDescription,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.infrared import (
    InfraredDeviceRegistrationCompleteEvent,
    InfraredHandleReceivedCodeAction,
    InfraredRegisterDeviceAction,
    InfraredSendCodeEvent,
    InfraredSetShouldPropagateAction,
    InfraredSetShouldReceiveAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import SELECTED_ITEM_PARAMETERS, UNSELECTED_ITEM_PARAMETERS
from ubo_app.utils.input import ubo_input
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
        generator = None
        try:
            generator = await send_command(
                'infrared',
                'receive',
                has_output_stream=True,
            )
            if generator is None:
                break
            try:
                async for response in generator:
                    if not _should_receive_keypad_actions():
                        # Break out if receiving was disabled
                        break
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
            except asyncio.CancelledError:
                # Properly close the generator when cancelled
                if generator is not None:
                    try:
                        await generator.aclose()
                    except (RuntimeError, asyncio.CancelledError):
                        # Generator might already be closing or cancelled, ignore
                        pass
                raise
            finally:
                # Always close the generator when exiting the loop normally
                # (either due to 'nocode' response or should_receive becoming False)
                if generator is not None:
                    try:
                        await generator.aclose()
                    except (RuntimeError, asyncio.CancelledError):
                        # Generator might already be closing or cancelled, ignore
                        pass
        except asyncio.CancelledError:
            # Re-raise cancellation to allow proper cleanup
            raise
        except Exception:
            logger.exception('Failed to send infrared receive command')
            # Don't re-raise, allow the loop to continue or exit naturally


async def _register_device(action: InfraredRegisterDeviceAction) -> None:
    """Handle register device action."""
    logger.info('Register Device button pressed')
    
    async def show_loading_page() -> None:
        """Show loading page with instructions and monitor registration progress."""
        loading_input_id: str | None = None
        monitor_task: asyncio.Task | None = None
        
        try:
            # Create loading page description with instructions
            loading_description = WebUIInputDescription(
                prompt='Registering Infrared Device',
                fields=[
                    InputFieldDescription(
                        name='instructions',
                        label='',
                        type=InputFieldType.LONG,
                        description=(
                            '📡 Point your infrared remote at the device\n\n'
                            '🔄 Send the same signal 5 times\n\n'
                            '💚 The RGB ring will blink green while waiting\n\n'
                            '✅ This page will close automatically when registration is complete'
                        ),
                        required=False,
                        default_value='Waiting for infrared signals...\n\nPlease send the same signal from your remote 5 times to register the device.',
                    ),
                ],
            )
            
            loading_input_id = loading_description.id
            
            # Monitor registration state in a separate task
            async def monitor_registration() -> None:
                """Monitor registration state and cancel loading page when complete."""
                # Wait a bit for the reducer to process the registration action
                await asyncio.sleep(0.1)
                
                # Wait until registration actually starts
                registration_started = False
                while not registration_started:
                    await asyncio.sleep(0.1)
                    current_state = store.get_state()
                    if current_state and hasattr(current_state, 'infrared'):
                        if current_state.infrared.is_registering_device:
                            registration_started = True
                            logger.info('Device registration started - monitoring for completion')
                            break
                
                # Now monitor for completion
                while True:
                    await asyncio.sleep(0.5)  # Check every 500ms
                    current_state = store.get_state()
                    if current_state and hasattr(current_state, 'infrared'):
                        is_registering = current_state.infrared.is_registering_device
                        if not is_registering and loading_input_id is not None:
                            # Registration completed, cancel the loading page
                            logger.info(
                                'Device registration complete - closing loading page',
                                extra={'input_id': loading_input_id},
                            )
                            store.dispatch(InputCancelAction(id=loading_input_id))
                            break
            
            # Start monitoring task
            monitor_task = create_task(monitor_registration())
            
            # Show the loading page (will be cancelled when registration completes)
            try:
                await ubo_input(
                    prompt='Registering Infrared Device',
                    descriptions=[loading_description],
                )
            except asyncio.CancelledError:
                logger.info('Loading page cancelled (registration complete or user cancelled)')
            finally:
                # Clean up monitoring task
                if monitor_task and not monitor_task.done():
                    monitor_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await monitor_task
            
        except Exception as e:
            logger.exception(
                'Error showing loading page for device registration',
                extra={'error': str(e)},
            )
            # Clean up monitoring task on error
            if monitor_task and not monitor_task.done():
                monitor_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor_task
    
    create_task(show_loading_page())


async def _handle_device_registration_complete(
    event: InfraredDeviceRegistrationCompleteEvent,
) -> None:
    """Handle device registration complete event - show UI buttons for input method selection."""
    try:
        logger.info(
            'Device registration complete handler reached',
            extra={
                'protocol': event.protocol,
                'scancode': event.scancode,
                'event_type': type(event).__name__,
            },
        )
    except Exception as e:
        logger.exception(
            'Error in device registration complete handler',
            extra={'error': str(e), 'event_type': type(event).__name__},
        )
        raise
    async def act() -> None:
        try:
            logger.info(
                'Device registration: Starting input collection',
                extra={
                    'protocol': event.protocol,
                    'scancode': event.scancode,
                },
            )
            device_name, _ = await ubo_input(
                prompt='Device Registered Successfully',
                descriptions=[
                    WebUIInputDescription(
                        fields=[
                            InputFieldDescription(
                                name='device_name',
                                label='Device Name',
                                type=InputFieldType.TEXT,
                                description=f'Enter a name for the device (Protocol: {event.protocol}, Code: {event.scancode})',
                                required=True,
                            ),
                        ],
                    ),
                    SpeechInputDescription(
                        instructions=ReadableInformation(
                            text=f'Say the name for the device (Protocol: {event.protocol}, Code: {event.scancode})',
                        ),
                    ),
                ],
            )
            logger.info(
                'Device registration: Device name received',
                extra={
                    'device_name': device_name,
                    'protocol': event.protocol,
                    'scancode': event.scancode,
                },
            )
        except asyncio.CancelledError:
            logger.info(
                'Device registration: Input collection cancelled',
                extra={
                    'protocol': event.protocol,
                    'scancode': event.scancode,
                },
            )
        except Exception as e:
            logger.exception(
                'Device registration: Error collecting device name',
                extra={
                    'protocol': event.protocol,
                    'scancode': event.scancode,
                    'error': str(e),
                },
            )

    create_task(act())


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
            UboDispatchItem(
                key='register_device',
                label='Register Device',
                icon='+',
                store_action=InfraredRegisterDeviceAction(),
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

    logger.info('Subscribing to InfraredDeviceRegistrationCompleteEvent')
    subscription = store.subscribe_event(
        InfraredDeviceRegistrationCompleteEvent,
        _handle_device_registration_complete,
    )
    logger.info(
        'Subscription created for InfraredDeviceRegistrationCompleteEvent',
        extra={'subscription': str(subscription)},
    )
    return [
        store.subscribe_event(InfraredSendCodeEvent, _send_code),
        store.subscribe_action(InfraredRegisterDeviceAction, _register_device),
        subscription,
    ]

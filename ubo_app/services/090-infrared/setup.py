"""Initialize the infrared service."""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
from typing import TYPE_CHECKING

from kivy.clock import Clock
from kivy.lang.builder import Builder
from kivy.properties import NumericProperty, StringProperty
from ubo_gui.menu.types import HeadlessMenu, Item, SubMenuItem

from ubo_app.logger import logger
from ubo_app.store.core.types import (
    CloseApplicationAction,
    MenuChooseByLabelAction,
    MenuGoBackAction,
    MenuGoBackEvent,
    MenuGoHomeEvent,
    OpenApplicationAction,
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    SpeechInputDescription,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.infrared import (
    InfraredAddDeviceAction,
    InfraredDevice,
    InfraredDeviceRegistrationCompleteEvent,
    InfraredDeviceRegistrationStartedEvent,
    InfraredHandleReceivedCodeAction,
    InfraredRegisterDeviceAction,
    InfraredRemoveDeviceAction,
    InfraredSendCodeAction,
    InfraredSendCodeEvent,
    InfraredSetIsRegisteringDeviceAction,
    InfraredSetShouldPropagateAction,
    InfraredSetShouldReceiveAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.ubo_actions import (
    UboApplicationItem,
    UboDispatchItem,
    register_application,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
    UboPageWidget,
    UboPromptWidget,
)
from ubo_app.utils.input import ubo_input
from ubo_app.utils.persistent_store import register_persistent_store
import json
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


@store.with_state(lambda state: state.infrared.should_receive_keypad_actions)
def _should_receive_keypad_actions(value: bool) -> bool:  # noqa: FBT001
    return value


def _is_ir_noise(protocol: str, scancode: str) -> bool:
    """Filter imon protocol noise: scancodes with fewer than 6 zero bits.

    Noise patterns like 0x7fffffff, 0x7ff7ffff, 0x7fbfffff have very few
    zero bits; real imon scancodes typically have more.
    """
    if protocol.lower() != 'imon':
        return False
    try:
        value = int(scancode, 0) & 0xFFFFFFFF
        ones = bin(value).count('1')
        zero_bits = 32 - ones
        return zero_bits < 6
    except (ValueError, TypeError):
        return False


ir_ctl_lock = asyncio.Lock()
ir_commands_queue = asyncio.Queue()

# Track the registration page instance ID
_registration_page_id: str | None = None




class InfraredRegistrationPage(UboPageWidget):
    """Page showing instructions for infrared device registration."""

    countdown: NumericProperty = NumericProperty(60)  # 60 second countdown
    countdown_text: StringProperty = StringProperty('Time remaining: 60s')
    _countdown_event: Clock.event | None = None

    def __init__(self, **kwargs: object) -> None:
        """Initialize the registration page."""
        super().__init__(**kwargs)
        global _registration_page_id
        _registration_page_id = self.id
        logger.info(
            'Infrared registration page opened',
            extra={'page_id': self.id},
        )
        # Start countdown timer
        self._start_countdown()
        # Bind countdown to update text
        self.bind(countdown=self._update_countdown_text)

    def _start_countdown(self) -> None:
        """Start the 60 second countdown timer."""
        self.countdown = 60
        self._update_countdown_text()
        self._countdown_event = Clock.schedule_interval(self._update_countdown, 1.0)

    def _update_countdown_text(self, *args: object) -> None:
        """Update the countdown text."""
        self.countdown_text = f'Time remaining: {int(self.countdown)}s'

    def _update_countdown(self, _dt: float) -> None:
        """Update the countdown timer."""
        self.countdown -= 1
        if self.countdown <= 0:
            self._timeout()

    def _timeout(self) -> None:
        """Handle timeout - cancel registration and close page."""
        logger.info('Registration timeout - cancelling registration')
        if self._countdown_event:
            self._countdown_event.cancel()
            self._countdown_event = None
        create_task(_cancel_registration())

    def on_leave(self) -> None:
        """Clean up when leaving the page."""
        if self._countdown_event:
            self._countdown_event.cancel()
            self._countdown_event = None


# Register the page as an application
register_application(
    application_id='infrared:registration',
    application=InfraredRegistrationPage,
)

# Load the KV file for the page
Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('registration_page.kv')
    .resolve()
    .as_posix(),
)


class RemoveDeviceConfirmPage(UboPromptWidget):
    """Confirmation page for removing an infrared device."""

    device_name: str = StringProperty('')
    protocol: str = StringProperty('')
    scancode: str = StringProperty('')

    def first_option_callback(self) -> None:
        """Yes: remove the device and close the page."""
        store.dispatch(
            InfraredRemoveDeviceAction(
                protocol=self.protocol,
                scancode=self.scancode,
            ),
        )
        store.dispatch(
            CloseApplicationAction(application_instance_id=self.id),
        )

    def second_option_callback(self) -> None:
        """Cancel: close the page without removing."""
        store.dispatch(
            CloseApplicationAction(application_instance_id=self.id),
        )

    def __init__(self, **kwargs: object) -> None:
        device_name = kwargs.pop('device_name', '')
        protocol = kwargs.pop('protocol', '')
        scancode = kwargs.pop('scancode', '')
        super().__init__(**kwargs)
        self.device_name = device_name
        self.protocol = protocol
        self.scancode = scancode
        self.prompt = f'Remove "{device_name}"?'
        self.first_option_label = 'Yes'
        self.first_option_icon = '󰆴'
        self.first_option_is_short = False
        self.second_option_label = 'Cancel'
        self.second_option_icon = '󰜺'
        self.second_option_is_short = False


register_application(
    application_id='infrared:remove-device-confirm',
    application=RemoveDeviceConfirmPage,
)


async def _send_code(action: InfraredSendCodeEvent) -> None:
    await ir_commands_queue.put(action)
    async with ir_ctl_lock:
        action = await ir_commands_queue.get()
        logger.info(
            'Sending infrared code via ir-ctl',
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
        if process.returncode != 0:
            logger.warning(
                'ir-ctl returned non-zero exit code',
                extra={
                    'protocol': action.protocol,
                    'scancode': action.scancode,
                    'returncode': process.returncode,
                },
            )
        else:
            logger.info(
                'Infrared code sent successfully',
                extra={'protocol': action.protocol, 'scancode': action.scancode},
            )
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
                    if _is_ir_noise(protocol, scancode):
                        continue
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


async def _register_device(_event: InfraredDeviceRegistrationStartedEvent) -> None:
    """Handle register device event - open registration page."""
    logger.info('Manage Keys - opening registration page')
    
    # Open the registration page
    store.dispatch(
        OpenApplicationAction(
            application_id='infrared:registration',
        ),
    )


async def _cancel_registration() -> None:
    """Cancel device registration."""
    logger.info('Cancelling device registration')
    
    # Stop registration
    store.dispatch(InfraredSetIsRegisteringDeviceAction(is_registering=False))
    
    # Close the registration page if it's open
    global _registration_page_id
    if _registration_page_id is not None:
        store.dispatch(
            CloseApplicationAction(application_instance_id=_registration_page_id),
        )
        _registration_page_id = None


async def _handle_device_registration_complete(
    event: InfraredDeviceRegistrationCompleteEvent,
) -> None:
    """Handle device registration complete event - close page and collect device name."""
    logger.info(
        'Device registration complete',
        extra={
            'protocol': event.protocol,
            'scancode': event.scancode,
        },
    )
    
    # Close the registration page
    global _registration_page_id
    if _registration_page_id is not None:
        store.dispatch(
            CloseApplicationAction(application_instance_id=_registration_page_id),
        )
        _registration_page_id = None
    
    # Collect device name
    async def collect_device_name() -> None:
        try:
            value, result = await ubo_input(
                prompt='Please enter device name on the Web UI',
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
            # For WebUI forms with fields, get the value from result.data
            # For speech input, use the value field directly
            if result and result.data:
                device_name = result.data.get('device_name', '').strip()
            else:
                device_name = (value or '').strip()
            
            if not device_name:
                logger.warning('Device registration: Device name is empty')
                return
            logger.info(
                'Device registration: Device name received',
                extra={
                    'device_name': device_name,
                    'protocol': event.protocol,
                    'scancode': event.scancode,
                },
            )
            # Add the device to the store
            store.dispatch(
                InfraredAddDeviceAction(
                    name=device_name,
                    protocol=event.protocol,
                    scancode=event.scancode,
                ),
            )
            logger.info(
                'Device registration: Device added to store',
                extra={
                    'device_name': device_name,
                    'protocol': event.protocol,
                    'scancode': event.scancode,
                },
            )
            # Navigate to Replay Devices so the user sees the new device
            store.dispatch(MenuGoBackAction())
            await asyncio.sleep(0.2)
            store.dispatch(MenuChooseByLabelAction(label='Replay Devices'))
        except asyncio.CancelledError:
            logger.info('Device registration: Input collection cancelled')
        except Exception as e:
            logger.exception(
                'Device registration: Error collecting device name',
                extra={'error': str(e)},
            )
    
    create_task(collect_device_name())


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
    register_persistent_store(
        'infrared_state:registered_devices',
        lambda state: json.dumps(
            [
                {
                    'name': device.name,
                    'protocol': device.protocol,
                    'scancode': device.scancode,
                }
                for device in state.infrared.registered_devices
            ]
        ),
    )

    @store.autorun(
        lambda state: state.infrared.registered_devices,
    )
    def remove_devices_menu(devices: list[InfraredDevice]) -> HeadlessMenu:
        """Create a menu with all registered devices for removal."""
        items: list[Item] = []
        for device in devices:
            items.append(
                UboApplicationItem(
                    key=f'remove_{device.protocol}_{device.scancode}',
                    label=device.name,
                    icon='-',
                    application_id='infrared:remove-device-confirm',
                    initialization_kwargs={
                        'device_name': device.name,
                        'protocol': device.protocol,
                        'scancode': device.scancode,
                    },
                ),
            )
        return HeadlessMenu(
            title='- Remove Devices',
            items=items,
            placeholder='No devices registered',
        )

    def manage_keys_menu() -> HeadlessMenu:
        """Menu for managing keys with Add and Remove options."""
        return HeadlessMenu(
            title='󰻅 Manage Keys',
            items=[
                UboDispatchItem(
                    key='add_keys',
                    label='Add Keys',
                    icon='+',
                    store_action=InfraredRegisterDeviceAction(),
                ),
                SubMenuItem(
                    key='remove_keys',
                    label='Remove Keys',
                    icon='-',
                    sub_menu=remove_devices_menu,
                ),
            ],
        )

    @store.autorun(
        lambda state: state.infrared.registered_devices,
    )
    def replay_devices_menu(devices: list[InfraredDevice]) -> HeadlessMenu:
        """Create a menu with all registered devices for replaying."""
        items: list[Item] = []
        for device in devices:
            items.append(
                UboDispatchItem(
                    key=f'replay_{device.protocol}_{device.scancode}',
                    label=device.name,
                    icon='󰻅',
                    store_action=InfraredSendCodeAction(
                        protocol=device.protocol,
                        scancode=device.scancode,
                    ),
                ),
            )
        return HeadlessMenu(
            title='󰑔Replay Devices',
            items=items,
            placeholder='No devices registered',
        )

    @store.autorun(
        lambda state: (
            state.infrared.should_propagate_keypad_actions,
            state.infrared.should_receive_keypad_actions,
        ),
    )
    def infrared_settings_menu(data: tuple[bool, bool]) -> HeadlessMenu:
        should_propagate_keypad_actions, should_receive_keypad_actions = data
        return HeadlessMenu(
            title='Settings',
            items=[
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
            ],
        )

    @store.autorun(
        lambda state: (
            state.infrared.should_propagate_keypad_actions,
            state.infrared.should_receive_keypad_actions,
        ),
    )
    def menu_items(data: tuple[bool, bool]) -> list[Item]:
        return [
            SubMenuItem(
                key='replay_devices',
                label='Replay Devices',
                icon='󰑔',
                sub_menu=replay_devices_menu,
            ),
            SubMenuItem(
                key='manage_keys',
                label='Manage Keys',
                icon='󰻅',
                sub_menu=manage_keys_menu(),
            ),
            SubMenuItem(
                key='settings',
                label='Settings',
                icon='',
                sub_menu=infrared_settings_menu,
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

    logger.info('Subscribing to InfraredDeviceRegistrationStartedEvent')
    registration_started_subscription = store.subscribe_event(
        InfraredDeviceRegistrationStartedEvent,
        _register_device,
    )
    
    logger.info('Subscribing to InfraredDeviceRegistrationCompleteEvent')
    registration_complete_subscription = store.subscribe_event(
        InfraredDeviceRegistrationCompleteEvent,
        _handle_device_registration_complete,
    )
    
    def handle_back_or_home(_event: MenuGoBackEvent | MenuGoHomeEvent) -> None:
        """Handle back/home events to cancel registration if in progress."""
        current_state = store.get_state()
        # Check if registration is in progress or if the registration page is open
        is_registering = (
            current_state
            and hasattr(current_state, 'infrared')
            and current_state.infrared.is_registering_device
        )
        global _registration_page_id
        page_is_open = _registration_page_id is not None
        
        if is_registering or page_is_open:
            create_task(_cancel_registration())
    
    logger.info('Subscribing to MenuGoBackEvent and MenuGoHomeEvent for registration cancellation')
    back_subscription = store.subscribe_event(MenuGoBackEvent, handle_back_or_home)
    home_subscription = store.subscribe_event(MenuGoHomeEvent, handle_back_or_home)
    
    return [
        store.subscribe_event(InfraredSendCodeEvent, _send_code),
        registration_started_subscription,
        registration_complete_subscription,
        back_subscription,
        home_subscription,
    ]

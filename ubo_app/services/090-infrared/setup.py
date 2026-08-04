"""Initialize the infrared service."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING

import ha

from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.bindable_actions import (
    BindableActionContext,
    get_bindable_action,
    get_bindable_actions,
    register_bindable_action,
    unregister_bindable_action,
)
from ubo_app.store.core.types import (
    CloseInstructionAction,
    MenuChooseByLabelAction,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPopAction,
    StackPushInstructionAction,
    StackPushPromptAction,
    UpdateDynamicMenuAction,
    UpdateInstructionProgressAction,
)
from ubo_app.store.core.types.view_data import MenuItemData
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.infrared import (
    InfraredAddDeviceAction,
    InfraredBoundActionTriggeredEvent,
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
from ubo_app.store.services.mqtt import (
    MqttPublishAction,
    MqttRequestAnnounceAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.menu_items import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
)
from ubo_app.utils.mqtt_registry import (
    register_mqtt_components,
)
from ubo_app.utils.persistent_store import register_persistent_store
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.services.mqtt import MqttComponent
    from ubo_app.utils.types import Subscriptions


@store.with_state(lambda state: state.infrared.should_receive_keypad_actions)
def _should_receive_keypad_actions(value: bool) -> bool:  # noqa: FBT001
    return value


MIN_ZERO_BITS_FOR_VALID_IMON = 6

# Dropdown label for "no bound action" (replay-only key).
NO_ACTION_LABEL = 'None'


def _is_ir_noise(protocol: str, scancode: str) -> bool:
    """Filter imon protocol noise: scancodes with fewer than 6 zero bits.

    Noise patterns like 0x7fffffff, 0x7ff7ffff, 0x7fbfffff have very few
    zero bits; real imon scancodes typically have more.
    """
    if protocol.lower() != 'imon':
        return False
    try:
        value = int(scancode, 0) & 0xFFFFFFFF
        ones = value.bit_count()
        zero_bits = 32 - ones
    except (ValueError, TypeError):
        return False
    else:
        return zero_bits < MIN_ZERO_BITS_FOR_VALID_IMON


ir_ctl_lock = asyncio.Lock()
ir_commands_queue = asyncio.Queue()



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


async def _wait_for_ir_code() -> None:  # noqa: C901
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
                    _publish_received(protocol, scancode)
            except asyncio.CancelledError:
                if generator is not None:
                    with contextlib.suppress(
                        RuntimeError,
                        asyncio.CancelledError,
                    ):
                        await generator.aclose()
                raise
            finally:
                if generator is not None:
                    with contextlib.suppress(
                        RuntimeError,
                        asyncio.CancelledError,
                    ):
                        await generator.aclose()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Failed to send infrared receive command')


_instruction_id: str | None = None


async def _register_device(_event: InfraredDeviceRegistrationStartedEvent) -> None:
    """Handle register device event - open instruction page."""
    logger.info('Manage Keys - opening registration instruction page')
    store.dispatch(
        StackPushInstructionAction(
            title='Registering Device',
            instruction=(
                'Point your infrared remote at the device'
                ' and send the same signal 5 times'
            ),
            spinner=True,
            timeout_seconds=60,
            footer_text='Press BACK to cancel',
        ),
    )

    @store.with_state(lambda state: state.main.stack)
    def _capture_id(stack: tuple) -> None:
        global _instruction_id  # noqa: PLW0603
        from ubo_app.store.core.types.stack_items import InstructionStackItem

        top = stack[-1] if stack else None
        if isinstance(top, InstructionStackItem):
            _instruction_id = top.id

    _capture_id()

    # Start countdown updates
    create_task(_run_instruction_countdown())


async def _run_instruction_countdown() -> None:
    """Run the 60s countdown, updating the instruction progress text."""
    for remaining in range(59, -1, -1):
        if _instruction_id is None:
            return
        store.dispatch(
            UpdateInstructionProgressAction(
                instruction_id=_instruction_id,
                progress_text=f'Time remaining: {remaining}s',
            ),
        )
        await asyncio.sleep(1)
    # Timeout — cancel registration
    await _cancel_registration()


def _close_instruction_page() -> None:
    """Close any instruction page on the stack."""
    global _instruction_id  # noqa: PLW0603
    if _instruction_id is not None:
        logger.info(
            'Closing instruction page: %s',
            _instruction_id,
        )
        store.dispatch(
            CloseInstructionAction(instruction_id=_instruction_id),
        )
        _instruction_id = None


async def _cancel_registration() -> None:
    """Cancel device registration."""
    logger.info('Cancelling device registration')
    store.dispatch(InfraredSetIsRegisteringDeviceAction(is_registering=False))
    _close_instruction_page()


async def _handle_device_registration_complete(
    event: InfraredDeviceRegistrationCompleteEvent,
) -> None:
    """Handle device registration complete event."""
    logger.info(
        'Device registration complete',
        extra={
            'protocol': event.protocol,
            'scancode': event.scancode,
        },
    )

    # Note: instruction page is still on the stack here. It gets cleaned
    # up inside collect_device_name() via StackPopAction(count=2) which
    # pops both the notification (from ubo_input) and the instruction.
    async def collect_device_name() -> None:
        try:
            # Build the action dropdown from the bindable-actions registry.
            # 'None' = a replay-only key (e.g. a TV power code) that triggers
            # no action when received. Labels are unique (registry guard), so
            # we can map the chosen label back to its stable key.
            label_to_key = {
                bindable.label: bindable.key
                for bindable in get_bindable_actions()
            }
            action_options = [NO_ACTION_LABEL, *label_to_key]

            value, result = await ubo_input(
                prompt='Please enter device name on the Web UI',
                descriptions=[
                    WebUIInputDescription(
                        fields=[
                            InputFieldDescription(
                                name='device_name',
                                label='Device Name',
                                type=InputFieldType.TEXT,
                                description=(
                                    f'Enter a name for the device'
                                    f' (Protocol: {event.protocol},'
                                    f' Code: {event.scancode})'
                                ),
                                required=True,
                            ),
                            InputFieldDescription(
                                name='description',
                                label='Description',
                                type=InputFieldType.TEXT,
                                description=(
                                    'Optional: what this key does'
                                    ' (e.g. turns the TV on/off)'
                                ),
                                required=False,
                            ),
                            InputFieldDescription(
                                name='bound_action_key',
                                label='Action',
                                type=InputFieldType.SELECT,
                                description=(
                                    'Optional: action to run when this key is'
                                    ' received'
                                ),
                                options=action_options,
                                default_value=NO_ACTION_LABEL,
                                required=False,
                            ),
                        ],
                    ),
                ],
            )
            data = result.data if result else {}
            if data:
                device_name = data.get('device_name', '').strip()
            else:
                device_name = (value or '').strip()
            description = (data.get('description', '') or '').strip() or None
            selected_label = data.get('bound_action_key', NO_ACTION_LABEL)
            bound_action_key = label_to_key.get(selected_label)

            if not device_name:
                logger.warning('Device registration: Device name is empty')
                return
            logger.info(
                'Device registration: Device name received',
                extra={
                    'device_name': device_name,
                    'protocol': event.protocol,
                    'scancode': event.scancode,
                    'bound_action_key': bound_action_key,
                },
            )
            store.dispatch(
                InfraredAddDeviceAction(
                    name=device_name,
                    protocol=event.protocol,
                    scancode=event.scancode,
                    description=description,
                    bound_action_key=bound_action_key,
                ),
            )
            # Pop notification + instruction, then navigate to Replay Keys
            await asyncio.sleep(0.5)
            store.dispatch(StackPopAction(count=2))
            await asyncio.sleep(0.5)
            store.dispatch(MenuChooseByLabelAction(label='Replay Keys'))
        except asyncio.CancelledError:
            logger.info('Device registration: Input collection cancelled')
            # Pop the orphaned notification stack item left by ubo_input,
            # plus the instruction page underneath it
            store.dispatch(StackPopAction(count=2))
        except Exception as e:
            logger.exception(
                'Device registration: Error collecting device name',
                extra={'error': str(e)},
            )

    create_task(collect_device_name())


def _handle_bound_action_triggered(
    event: InfraredBoundActionTriggeredEvent,
) -> None:
    """Resolve a device's bound action against the registry and dispatch it.

    Mirrors the action-registry side-effect pattern (``_handle_execute_menu_action``):
    the reducer stays pure and emits the event; this handler does the lookup and
    dispatch.
    """
    bindable = get_bindable_action(event.bound_action_key)
    if bindable is None:
        logger.warning(
            'No bindable action registered for key',
            extra={'bound_action_key': event.bound_action_key},
        )
        return
    try:
        triggered_action = bindable.factory(
            BindableActionContext(
                protocol=event.protocol,
                scancode=event.scancode,
                device_name=event.device_name,
            ),
        )
    except Exception:
        logger.exception(
            'Bindable action factory failed',
            extra={'bound_action_key': event.bound_action_key},
        )
        return
    logger.info(
        'Triggered bound action: %s',
        type(triggered_action).__name__,
    )
    store.dispatch(triggered_action)


# Bindable-action keys currently registered for managed IR devices.
_registered_send_keys: set[str] = set()


def _register_receive_bindable_actions() -> None:
    """Expose IR receive on/off as bindable actions (e.g. for voice commands)."""
    register_bindable_action(
        'infrared:receive-on',
        'Infrared: Start Receiving',
        lambda _ctx: InfraredSetShouldReceiveAction(should_receive=True),
        allow_reregister=True,
    )
    register_bindable_action(
        'infrared:receive-off',
        'Infrared: Stop Receiving',
        lambda _ctx: InfraredSetShouldReceiveAction(should_receive=False),
        allow_reregister=True,
    )


def _sync_send_bindable_actions(devices: list[InfraredDevice]) -> None:
    """Keep one ``infrared:send:*`` bindable action per managed device.

    Registered via an autorun so it also fires on startup with the persisted
    device list. Registry labels must be unique, so a colliding device name is
    disambiguated with its scancode.
    """
    seen_labels: set[str] = set()
    desired: dict[str, tuple[str, InfraredDevice]] = {}
    for device in devices:
        key = f'infrared:send:{device.protocol}:{device.scancode}'
        label = f'IR Send: {device.name}'
        if label in seen_labels:
            label = f'{label} ({device.scancode})'
        seen_labels.add(label)
        desired[key] = (label, device)

    for stale_key in _registered_send_keys - desired.keys():
        unregister_bindable_action(stale_key)

    _registered_send_keys.clear()
    for key, (label, device) in desired.items():
        register_bindable_action(
            key,
            label,
            lambda _ctx, d=device: InfraredSendCodeAction(
                protocol=d.protocol,
                scancode=d.scancode,
            ),
            allow_reregister=True,
        )
        _registered_send_keys.add(key)


def _register_core_actions() -> None:
    """Register core action handlers for the infrared service."""

    @store.with_state(lambda state: state.infrared.should_propagate_keypad_actions)
    def _toggle_propagate(current: bool) -> None:  # noqa: FBT001
        store.dispatch(
            InfraredSetShouldPropagateAction(
                should_propagate=not current,
            ),
        )

    @store.with_state(lambda state: state.infrared.should_receive_keypad_actions)
    def _toggle_receive(current: bool) -> None:  # noqa: FBT001
        store.dispatch(
            InfraredSetShouldReceiveAction(
                should_receive=not current,
            ),
        )

    def _start_registration() -> None:
        store.dispatch(InfraredRegisterDeviceAction())

    register_action('infrared:toggle-propagate', _toggle_propagate)
    register_action('infrared:toggle-receive', _toggle_receive)
    register_action('infrared:start-registration', _start_registration)
    register_action(
        'infrared:cancel-registration',
        lambda: create_task(_cancel_registration()),
    )
    def _pop_and_remove_device(action_id: str) -> None:
        """Handle pop + remove device from prompt Yes button."""
        # action_id format: infrared:pop-and-remove-device:{protocol}:{scancode}
        parts = action_id.split(':')
        if len(parts) >= 4:  # noqa: PLR2004
            protocol = parts[2]
            scancode = parts[3]
            store.dispatch(StackPopAction())
            store.dispatch(
                InfraredRemoveDeviceAction(
                    protocol=protocol,
                    scancode=scancode,
                ),
            )

    register_action('infrared:pop-and-remove-device:*', _pop_and_remove_device)

    def _pop_stack() -> None:
        store.dispatch(StackPopAction())

    register_action('stack:pop', _pop_stack)


def _register_menus_and_actions() -> None:  # noqa: C901
    """Register all menus, actions, and path matchers for the infrared service."""
    _register_core_actions()
    _register_receive_bindable_actions()

    # Expose each managed device as an `infrared:send:*` bindable action so it
    # can be bound to other triggers (e.g. a voice command). The autorun also
    # fires on startup with the persisted device list.
    @store.autorun(lambda state: state.infrared.registered_devices)
    def _sync_send_actions(devices: list[InfraredDevice]) -> None:
        _sync_send_bindable_actions(devices)

    # Register remove-device action handlers dynamically
    @store.autorun(lambda state: state.infrared.registered_devices)
    def _register_remove_actions(devices: list[InfraredDevice]) -> None:
        for device in devices:
            action_id = (
                f'infrared:remove-device:{device.protocol}:{device.scancode}'
            )
            register_action(
                action_id,
                lambda d=device: store.dispatch(
                    InfraredRemoveDeviceAction(
                        protocol=d.protocol,
                        scancode=d.scancode,
                    ),
                ),
                allow_reregister=True,
            )

    # Register replay-device action handlers dynamically
    @store.autorun(lambda state: state.infrared.registered_devices)
    def _register_replay_actions(devices: list[InfraredDevice]) -> None:
        for device in devices:
            action_id = (
                f'infrared:replay-device:{device.protocol}:{device.scancode}'
            )
            register_action(
                action_id,
                lambda d=device: store.dispatch(
                    InfraredSendCodeAction(
                        protocol=d.protocol,
                        scancode=d.scancode,
                    ),
                ),
                allow_reregister=True,
            )

    # Menu: Remove Devices (dynamic)
    @store.autorun(lambda state: state.infrared.registered_devices)
    def _update_remove_devices_menu(devices: list[InfraredDevice]) -> None:
        items = tuple(
            MenuItemData(
                key=f'remove_{device.protocol}_{device.scancode}',
                label=device.name,
                icon='󰖧',
                action_id=(
                    f'infrared:open-remove-confirm'
                    f':{device.protocol}:{device.scancode}'
                ),
            )
            for device in devices
        )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='infrared:remove-devices',
                title='Remove Keys',
                items=items,
                placeholder='No devices registered',
            ),
        )

    # Register open-remove-confirm action handlers dynamically
    @store.autorun(lambda state: state.infrared.registered_devices)
    def _register_open_remove_confirm_actions(
        devices: list[InfraredDevice],
    ) -> None:
        for device in devices:
            action_id = (
                f'infrared:open-remove-confirm'
                f':{device.protocol}:{device.scancode}'
            )
            register_action(
                action_id,
                lambda d=device: store.dispatch(
                    StackPushPromptAction(
                        title='Remove Key',
                        prompt=f'Remove "{d.name}"?',
                        icon='󰆴',
                        items=(
                            MenuItemData(
                                key='yes',
                                label='Yes',
                                icon='󰆴',
                                action_id=(
                                    f'infrared:pop-and-remove-device'
                                    f':{d.protocol}:{d.scancode}'
                                ),
                            ),
                            MenuItemData(
                                key='cancel',
                                label='Cancel',
                                icon='󰜺',
                                action_id='stack:pop',
                            ),
                        ),
                    ),
                ),
                allow_reregister=True,
            )

    # Menu: Replay Devices (dynamic)
    @store.autorun(lambda state: state.infrared.registered_devices)
    def _update_replay_devices_menu(devices: list[InfraredDevice]) -> None:
        items = tuple(
            MenuItemData(
                key=f'replay_{device.protocol}_{device.scancode}',
                label=device.name,
                icon='󰖧',
                action_id=(
                    f'infrared:replay-device'
                    f':{device.protocol}:{device.scancode}'
                ),
            )
            for device in devices
        )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='infrared:replay-devices',
                title='Replay Keys',
                items=items,
                placeholder='No devices registered',
            ),
        )

    # Settings menu (Propagate / Receive toggles)
    @store.autorun(
        lambda state: (
            state.infrared.should_propagate_keypad_actions,
            state.infrared.should_receive_keypad_actions,
        ),
    )
    def _update_settings_menu(data: tuple[bool, bool]) -> None:
        should_propagate_keypad_actions, should_receive_keypad_actions = data
        items = (
            MenuItemData(
                key='receive_keys',
                label='Receive Keys',
                action_id='infrared:toggle-receive',
                **(
                    SELECTED_ITEM_PARAMETERS
                    if should_receive_keypad_actions
                    else UNSELECTED_ITEM_PARAMETERS
                ),
            ),
            MenuItemData(
                key='propagate_keys',
                label='Propagate Keys',
                action_id='infrared:toggle-propagate',
                **(
                    SELECTED_ITEM_PARAMETERS
                    if should_propagate_keypad_actions
                    else UNSELECTED_ITEM_PARAMETERS
                ),
            ),
        )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='infrared:ir-settings',
                title='Settings',
                items=items,
            ),
        )

    # Main infrared menu items
    @store.autorun(
        lambda state: (
            state.infrared.should_propagate_keypad_actions,
            state.infrared.should_receive_keypad_actions,
        ),
    )
    def menu_items(_data: tuple[bool, bool]) -> None:
        items = (
            MenuItemData(
                key='infrared:replay-devices',
                label='Replay Keys',
                icon='󰑔',
                action_id='menu:select:infrared:replay-devices',
            ),
            MenuItemData(
                key='infrared:manage-keys',
                label='Manage Keys',
                icon='󰻅',
                action_id='menu:select:infrared:manage-keys',
            ),
            MenuItemData(
                key='infrared:ir-settings',
                label='Settings',
                icon='',
                action_id='menu:select:infrared:ir-settings',
            ),
        )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='infrared:main',
                title='Infrared',
                items=items,
            ),
        )

    # Manage Keys submenu
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id='infrared:manage-keys',
            title='Manage Keys',
            items=(
                MenuItemData(
                    key='add_keys',
                    label='Add Keys',
                    icon='',
                    action_id='infrared:start-registration',
                ),
                MenuItemData(
                    key='infrared:remove-devices',
                    label='Remove Keys',
                    icon='󰆴',
                    action_id='menu:select:infrared:remove-devices',
                ),
            ),
        ),
    )

    # Register path matchers for Infrared menu navigation
    from ubo_app.store.core.view_registry import register_path_menu_matcher

    def _infrared_path_matcher(path: tuple[str, ...]) -> str | None:
        """Match all infrared menu paths to their dynamic menu IDs."""
        if len(path) < 4 or path[3] != 'infrared:infrared':  # noqa: PLR2004
            return None
        # Deepest paths first to avoid prefix match ambiguity
        if (
            len(path) == 6  # noqa: PLR2004
            and path[4] == 'infrared:manage-keys'
            and path[5] == 'infrared:remove-devices'
        ):
            return 'infrared:remove-devices'
        if len(path) == 5:  # noqa: PLR2004
            match path[4]:
                case 'infrared:manage-keys':
                    return 'infrared:manage-keys'
                case 'infrared:replay-devices':
                    return 'infrared:replay-devices'
                case 'infrared:ir-settings':
                    return 'infrared:ir-settings'
        if len(path) == 4:  # noqa: PLR2004
            return 'infrared:main'
        return None

    register_path_menu_matcher(
        'infrared:paths',
        _infrared_path_matcher,
        priority=1,
    )



@store.with_state(lambda state: state.infrared.registered_devices)
def _mqtt_components(devices: Sequence[InfraredDevice]) -> list[MqttComponent]:
    """Describe the pod's infrared entities whenever the bridge (re)announces."""
    return ha.components(devices)


def _announce_devices(_: Sequence[InfraredDevice]) -> None:
    """Re-announce when a device is registered or removed.

    The button set is derived from the registry, so without this a newly taught
    remote has no entity in Home Assistant until the next reconnect.
    """
    store.dispatch(MqttRequestAnnounceAction())


@store.with_state(lambda state: state.infrared.registered_devices)
def _publish_received(
    devices: Sequence[InfraredDevice],
    protocol: str,
    scancode: str,
) -> None:
    """Report a received code to Home Assistant as an event.

    Dropped by the bridge when MQTT is off or disconnected, so this costs
    nothing when nobody is listening.
    """
    store.dispatch(
        MqttPublishAction(
            channel=ha.RECEIVED_CHANNEL,
            payload=ha.received_payload(protocol, scancode, devices),
        ),
    )


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

    persistence_cleanups = [
        register_persistent_store(
            'infrared_state:should_propagate_keypad_actions',
            lambda state: state.infrared.should_propagate_keypad_actions,
        ),
        register_persistent_store(
            'infrared_state:should_receive_keypad_actions',
            lambda state: state.infrared.should_receive_keypad_actions,
        ),
        register_persistent_store(
            'infrared_state:registered_devices',
            lambda state: json.dumps(
                [
                    {
                        'name': device.name,
                        'protocol': device.protocol,
                        'scancode': device.scancode,
                        'description': device.description,
                        'bound_action_key': device.bound_action_key,
                    }
                    for device in state.infrared.registered_devices
                ],
            ),
        ),
    ]

    _register_menus_and_actions()

    store.dispatch(
        RegisterSettingAppAction(
            key='infrared',
            category=SettingsCategory.HARDWARE,
            label='Infrared',
            icon='󰻅',
        ),
    )

    unregister_components = register_mqtt_components('infrared', _mqtt_components)
    # Subscribed here rather than at import: a module-level `@store.autorun`
    # registers a listener the moment the file is imported.
    announce_devices = store.autorun(
        lambda state: state.infrared.registered_devices,
    )(_announce_devices)

    return [
        *persistence_cleanups,
        unregister_components,
        announce_devices.unsubscribe,
        store.subscribe_event(InfraredSendCodeEvent, _send_code),
        store.subscribe_event(
            InfraredDeviceRegistrationStartedEvent,
            _register_device,
        ),
        store.subscribe_event(
            InfraredDeviceRegistrationCompleteEvent,
            _handle_device_registration_complete,
        ),
        store.subscribe_event(
            InfraredBoundActionTriggeredEvent,
            _handle_bound_action_triggered,
        ),
    ]

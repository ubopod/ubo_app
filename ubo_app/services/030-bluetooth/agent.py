# pyright: reportMissingModuleSource=false
"""BlueZ pairing agent.

Implements ``org.bluez.Agent1`` with the ``DisplayYesNo`` capability: when a
device requests pairing, the 6-digit passkey is shown on the Ubo screen and the
user confirms (or rejects) it with the keypad.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from bluetooth_interfaces import BLUEZ_SERVICE, BluezAgentManagerInterface
from constants import (
    BLUETOOTH_AGENT_CAPABILITY,
    BLUETOOTH_AGENT_PATH,
    BLUETOOTH_ICON,
    PAIRING_CONFIRMATION_TIMEOUT,
)
from sdbus import (  # pyright: ignore [reportMissingModuleSource]
    DbusFailedError,
    DbusInterfaceCommonAsync,
    dbus_method_async,
)

from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    StackPopAction,
    StackPushPromptAction,
)
from ubo_app.store.main import store
from ubo_app.utils import IS_RPI
from ubo_app.utils.bus_provider import get_system_bus
from ubo_app.utils.error_handlers import report_service_error

# AgentManager1 lives at the BlueZ root object.
AGENT_MANAGER_PATH = '/org/bluez'


class BluezRejectedError(DbusFailedError):
    """Raised to tell BlueZ the user rejected a pairing request."""

    dbus_error_name = 'org.bluez.Error.Rejected'


class BluezCanceledError(DbusFailedError):
    """Raised to tell BlueZ a pairing request was canceled."""

    dbus_error_name = 'org.bluez.Error.Canceled'


@dataclass(kw_only=True)
class _PendingConfirmation:
    """A pairing confirmation awaiting the user's decision."""

    future: asyncio.Future[bool]
    loop: asyncio.AbstractEventLoop


# Module-level singletons (no globals): the in-flight confirmation and a
# reference to the exported agent object so it is not garbage-collected.
_pending: list[_PendingConfirmation | None] = [None]
_agent_holder: list[BluetoothAgent | None] = [None]


def resolve_pairing_confirmation(*, accepted: bool) -> None:
    """Resolve the in-flight pairing confirmation from a menu action handler."""
    pending = _pending[0]
    if pending is None or pending.future.done():
        return
    pending.loop.call_soon_threadsafe(pending.future.set_result, accepted)


def _cancel_pending() -> None:
    """Reject the in-flight pairing confirmation, if any."""
    resolve_pairing_confirmation(accepted=False)


class BluetoothAgent(
    DbusInterfaceCommonAsync,
    interface_name='org.bluez.Agent1',
):
    """A ``DisplayYesNo`` pairing agent exported on the system bus."""

    @dbus_method_async(method_name='Release')
    async def release(self: BluetoothAgent) -> None:
        """Handle BlueZ releasing (unregistering) the agent."""
        logger.info('Bluetooth pairing agent released')

    @dbus_method_async(
        input_signature='o',
        result_signature='s',
        method_name='RequestPinCode',
    )
    async def request_pin_code(self: BluetoothAgent, device: str) -> str:
        """PIN-code entry is unsupported by a DisplayYesNo agent."""
        logger.warning('Bluetooth PIN code requested', extra={'device': device})
        raise BluezRejectedError

    @dbus_method_async(input_signature='os', method_name='DisplayPinCode')
    async def display_pin_code(
        self: BluetoothAgent,
        device: str,
        pincode: str,
    ) -> None:
        """Informational: BlueZ asks us to display a PIN code."""
        logger.info(
            'Bluetooth PIN code',
            extra={'device': device, 'pincode': pincode},
        )

    @dbus_method_async(
        input_signature='o',
        result_signature='u',
        method_name='RequestPasskey',
    )
    async def request_passkey(self: BluetoothAgent, device: str) -> int:
        """Passkey entry is unsupported by a DisplayYesNo agent."""
        logger.warning('Bluetooth passkey requested', extra={'device': device})
        raise BluezRejectedError

    @dbus_method_async(input_signature='ouq', method_name='DisplayPasskey')
    async def display_passkey(
        self: BluetoothAgent,
        device: str,
        passkey: int,
        entered: int,
    ) -> None:
        """Informational: BlueZ asks us to display a passkey."""
        logger.info(
            'Bluetooth passkey display',
            extra={'device': device, 'passkey': passkey, 'entered': entered},
        )

    @dbus_method_async(input_signature='ou', method_name='RequestConfirmation')
    async def request_confirmation(
        self: BluetoothAgent,
        device: str,
        passkey: int,
    ) -> None:
        """Ask the user to confirm a 6-digit pairing passkey."""
        logger.info(
            'Bluetooth pairing confirmation requested',
            extra={'device': device, 'passkey': passkey},
        )
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        _cancel_pending()
        _pending[0] = _PendingConfirmation(future=future, loop=loop)

        store.dispatch(
            StackPushPromptAction(
                title='Bluetooth Pairing',
                prompt=f'Confirm code:\n{passkey:06d}',
                icon=BLUETOOTH_ICON,
                items=(
                    MenuItemData(
                        key='confirm',
                        label='Confirm',
                        icon='󰄬',
                        action_id='bluetooth:pairing-confirm',
                    ),
                    MenuItemData(
                        key='reject',
                        label='Reject',
                        icon='󰜺',
                        action_id='bluetooth:pairing-reject',
                    ),
                ),
            ),
        )

        try:
            accepted = await asyncio.wait_for(
                future,
                timeout=PAIRING_CONFIRMATION_TIMEOUT,
            )
        except (TimeoutError, asyncio.CancelledError):
            accepted = False
        finally:
            _pending[0] = None
            store.dispatch(StackPopAction())

        if not accepted:
            logger.info('Bluetooth pairing rejected', extra={'device': device})
            raise BluezRejectedError

        logger.info('Bluetooth pairing confirmed', extra={'device': device})

    @dbus_method_async(input_signature='o', method_name='RequestAuthorization')
    async def request_authorization(self: BluetoothAgent, device: str) -> None:
        """Auto-authorize: the pairing was initiated from the Ubo menu."""
        logger.info('Bluetooth pairing authorized', extra={'device': device})

    @dbus_method_async(input_signature='os', method_name='AuthorizeService')
    async def authorize_service(
        self: BluetoothAgent,
        device: str,
        uuid: str,
    ) -> None:
        """Auto-authorize the requested service profile."""
        logger.info(
            'Bluetooth service authorized',
            extra={'device': device, 'uuid': uuid},
        )

    @dbus_method_async(method_name='Cancel')
    async def cancel(self: BluetoothAgent) -> None:
        """Handle BlueZ canceling the current pairing request."""
        logger.info('Bluetooth pairing request canceled')
        _cancel_pending()


async def register_agent() -> None:
    """Export the pairing agent and register it as the system default."""
    if not IS_RPI:
        return
    bus = get_system_bus()
    agent = BluetoothAgent()
    try:
        agent.export_to_dbus(BLUETOOTH_AGENT_PATH, bus)
    except Exception:
        logger.exception('Failed to export Bluetooth pairing agent')
        report_service_error()
        return
    _agent_holder[0] = agent

    manager = BluezAgentManagerInterface.new_proxy(
        bus=bus,
        service_name=BLUEZ_SERVICE,
        object_path=AGENT_MANAGER_PATH,
    )
    try:
        await manager.register_agent(
            BLUETOOTH_AGENT_PATH,
            BLUETOOTH_AGENT_CAPABILITY,
        )
        await manager.request_default_agent(BLUETOOTH_AGENT_PATH)
        logger.info('Bluetooth pairing agent registered')
    except Exception:
        logger.exception('Failed to register Bluetooth pairing agent')
        report_service_error()


async def unregister_agent() -> None:
    """Unregister the pairing agent (service shutdown)."""
    if not IS_RPI:
        return
    _cancel_pending()
    with contextlib.suppress(Exception):
        manager = BluezAgentManagerInterface.new_proxy(
            bus=get_system_bus(),
            service_name=BLUEZ_SERVICE,
            object_path=AGENT_MANAGER_PATH,
        )
        await manager.unregister_agent(BLUETOOTH_AGENT_PATH)
    _agent_holder[0] = None

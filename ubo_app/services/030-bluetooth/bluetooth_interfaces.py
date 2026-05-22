"""Hand-rolled BlueZ D-Bus interface definitions.

BlueZ exposes a small, stable D-Bus API. Rather than depend on the
work-in-progress ``python-sdbus-bluez`` package, the bluetooth service defines
the BlueZ-specific interfaces it needs directly, following the same pattern
used by ``ubo_app/utils/dbus_interfaces.py``.

The ``org.freedesktop.DBus.ObjectManager`` interface is *not* hand-rolled: it
is a standard D-Bus interface that sdbus ships built-in, so it is aliased from
``sdbus.DbusObjectManagerInterfaceAsync`` (see ``DbusObjectManagerInterface``
below).

D-Bus member names are passed explicitly so the bindings never rely on
sdbus' snake_case-to-CamelCase auto-conversion (which would mangle names such
as ``RSSI``).
"""

from __future__ import annotations

from sdbus import (  # pyright: ignore [reportMissingModuleSource]
    DbusInterfaceCommonAsync,
    DbusObjectManagerInterfaceAsync,
    dbus_method_async,
    dbus_property_async,
)

# BlueZ D-Bus service name and well-known object paths.
BLUEZ_SERVICE = 'org.bluez'
BLUEZ_ROOT_PATH = '/'
BLUEZ_ADAPTER_PATH = '/org/bluez/hci0'

# D-Bus interface names.
ADAPTER_INTERFACE = 'org.bluez.Adapter1'
DEVICE_INTERFACE = 'org.bluez.Device1'
AGENT_MANAGER_INTERFACE = 'org.bluez.AgentManager1'
OBJECT_MANAGER_INTERFACE = 'org.freedesktop.DBus.ObjectManager'


class BluezAdapterInterface(
    DbusInterfaceCommonAsync,
    interface_name=ADAPTER_INTERFACE,
):
    """Proxy for ``org.bluez.Adapter1`` (the Bluetooth controller)."""

    @dbus_method_async(method_name='StartDiscovery')
    async def start_discovery(self: BluezAdapterInterface) -> None:
        """Start scanning for nearby devices."""
        raise NotImplementedError

    @dbus_method_async(method_name='StopDiscovery')
    async def stop_discovery(self: BluezAdapterInterface) -> None:
        """Stop scanning for nearby devices."""
        raise NotImplementedError

    @dbus_method_async(input_signature='o', method_name='RemoveDevice')
    async def remove_device(self: BluezAdapterInterface, device: str) -> None:
        """Remove (unpair and forget) a device by its object path."""
        raise NotImplementedError

    @dbus_method_async(input_signature='a{sv}', method_name='SetDiscoveryFilter')
    async def set_discovery_filter(
        self: BluezAdapterInterface,
        discovery_filter: dict[str, tuple[str, object]],
    ) -> None:
        """Set the discovery filter (transport, RSSI threshold, ...)."""
        raise NotImplementedError

    @dbus_property_async(property_signature='b', property_name='Powered')
    def powered(self: BluezAdapterInterface) -> bool:
        """Whether the adapter is powered on."""
        raise NotImplementedError

    @dbus_property_async(property_signature='b', property_name='Discovering')
    def discovering(self: BluezAdapterInterface) -> bool:
        """Whether the adapter is currently scanning."""
        raise NotImplementedError

    @dbus_property_async(property_signature='s', property_name='Address')
    def address(self: BluezAdapterInterface) -> str:
        """Return the adapter's Bluetooth address."""
        raise NotImplementedError


class BluezDeviceInterface(
    DbusInterfaceCommonAsync,
    interface_name=DEVICE_INTERFACE,
):
    """Proxy for ``org.bluez.Device1`` (a remote Bluetooth device)."""

    @dbus_method_async(method_name='Pair')
    async def pair(self: BluezDeviceInterface) -> None:
        """Pair with the device (triggers the registered agent)."""
        raise NotImplementedError

    @dbus_method_async(method_name='CancelPairing')
    async def cancel_pairing(self: BluezDeviceInterface) -> None:
        """Cancel an in-progress pairing attempt."""
        raise NotImplementedError

    @dbus_method_async(method_name='Connect')
    async def connect(self: BluezDeviceInterface) -> None:
        """Connect to the (paired) device."""
        raise NotImplementedError

    @dbus_method_async(method_name='Disconnect')
    async def disconnect(self: BluezDeviceInterface) -> None:
        """Disconnect from the device."""
        raise NotImplementedError

    @dbus_property_async(property_signature='s', property_name='Address')
    def address(self: BluezDeviceInterface) -> str:
        """Return the device's Bluetooth address."""
        raise NotImplementedError

    @dbus_property_async(property_signature='s', property_name='Name')
    def name(self: BluezDeviceInterface) -> str:
        """Return the device's reported name."""
        raise NotImplementedError

    @dbus_property_async(property_signature='s', property_name='Alias')
    def alias(self: BluezDeviceInterface) -> str:
        """Return the device's alias (falls back to name)."""
        raise NotImplementedError

    @dbus_property_async(property_signature='s', property_name='Icon')
    def icon(self: BluezDeviceInterface) -> str:
        """Freedesktop icon hint (e.g. ``audio-card``, ``input-keyboard``)."""
        raise NotImplementedError

    @dbus_property_async(property_signature='b', property_name='Paired')
    def paired(self: BluezDeviceInterface) -> bool:
        """Whether the device is paired."""
        raise NotImplementedError

    @dbus_property_async(property_signature='b', property_name='Connected')
    def connected(self: BluezDeviceInterface) -> bool:
        """Whether the device is currently connected."""
        raise NotImplementedError

    @dbus_property_async(property_signature='b', property_name='Trusted')
    def trusted(self: BluezDeviceInterface) -> bool:
        """Whether the device is trusted (auto-reconnect allowed)."""
        raise NotImplementedError

    @dbus_property_async(property_signature='n', property_name='RSSI')
    def rssi(self: BluezDeviceInterface) -> int:
        """Received signal strength, in dBm (only set while discovering)."""
        raise NotImplementedError


class BluezAgentManagerInterface(
    DbusInterfaceCommonAsync,
    interface_name=AGENT_MANAGER_INTERFACE,
):
    """Proxy for ``org.bluez.AgentManager1`` (pairing agent registration)."""

    @dbus_method_async(input_signature='os', method_name='RegisterAgent')
    async def register_agent(
        self: BluezAgentManagerInterface,
        agent: str,
        capability: str,
    ) -> None:
        """Register a pairing agent at the given object path."""
        raise NotImplementedError

    @dbus_method_async(input_signature='o', method_name='UnregisterAgent')
    async def unregister_agent(
        self: BluezAgentManagerInterface,
        agent: str,
    ) -> None:
        """Unregister a previously registered pairing agent."""
        raise NotImplementedError

    @dbus_method_async(input_signature='o', method_name='RequestDefaultAgent')
    async def request_default_agent(
        self: BluezAgentManagerInterface,
        agent: str,
    ) -> None:
        """Make the given agent the system-wide default."""
        raise NotImplementedError


# ``org.freedesktop.DBus.ObjectManager`` is a standard D-Bus interface that
# sdbus already ships built-in. Declaring a second class with that interface
# name raises ``ValueError: D-Bus interface ... was already created`` at import
# time, so the built-in is aliased rather than hand-rolled. It provides
# ``get_managed_objects()`` plus the ``interfaces_added`` / ``interfaces_removed``
# signals — used to enumerate adapters/devices and live-track them during
# discovery.
DbusObjectManagerInterface = DbusObjectManagerInterfaceAsync

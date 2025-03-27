"""DBus interfaces."""

from __future__ import annotations

from sdbus import (  # pyright: ignore [reportMissingModuleSource]
    DbusInterfaceCommonAsync,
    dbus_method_async,
    dbus_property_async,
    dbus_signal_async,
)


class AccountsInterface(
    DbusInterfaceCommonAsync,
    interface_name='org.freedesktop.Accounts',
):
    """DBus interface for managing user accounts."""

    @dbus_method_async(result_signature='ao')
    async def list_cached_users(self: AccountsInterface) -> list[str]:
        """List the cached users."""
        raise NotImplementedError

    @dbus_signal_async('o')
    def user_added(self) -> str:
        """Signal emitted when a user is added."""
        raise NotImplementedError

    @dbus_signal_async('o')
    def user_deleted(self) -> str:
        """Signal emitted when a user is deleted."""
        raise NotImplementedError


class UserInterface(
    DbusInterfaceCommonAsync,
    interface_name='org.freedesktop.Accounts.User',
):
    """DBus interface for querying user information."""

    @dbus_property_async(property_signature='s')
    def user_name(self: UserInterface) -> str:
        """Return the user name."""
        raise NotImplementedError


class SystemdUnitInterface(
    DbusInterfaceCommonAsync,
    interface_name='org.freedesktop.systemd1.Unit',
):
    """DBus interface for managing systemd units."""

    @dbus_property_async(property_signature='s')
    def active_state(self: SystemdUnitInterface) -> str:
        """Return the active state of the unit."""
        raise NotImplementedError

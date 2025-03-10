# pyright: reportMissingModuleSource=false
"""Provides the system bus for the application."""

from __future__ import annotations

from threading import Thread, current_thread

from sdbus import SdBus, sd_bus_open_system, sd_bus_open_user, set_default_bus

system_buses: dict[Thread, SdBus] = {}
user_buses: dict[Thread, SdBus] = {}


def clean_up() -> None:
    """Cleanup the buses."""
    for bus in system_buses.values():
        bus.close()
    system_buses.clear()
    for bus in user_buses.values():
        bus.close()
    user_buses.clear()


def get_system_bus() -> SdBus:
    """Get the system bus for current thread."""
    thread = current_thread()
    if thread not in system_buses:
        system_buses[thread] = sd_bus_open_system()
    set_default_bus(system_buses[thread])
    return system_buses[thread]


def get_user_bus() -> SdBus:
    """Get the system bus for current thread."""
    thread = current_thread()
    if thread not in user_buses:
        user_buses[thread] = sd_bus_open_user()
    return user_buses[thread]

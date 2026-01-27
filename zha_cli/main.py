"""Main entry point for the ZHA CLI tool."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from typing import Any

from zha_cli import ui
from zha_cli.coordinator_probe import DetectedCoordinator, discover_coordinators
from zha_cli.device_control import DeviceController
from zha_cli.device_pairing import DevicePairingManager
from zha_cli.network_manager import NetworkManager

_LOGGER = logging.getLogger(__name__)


class ZHACli:
    """ZHA CLI application."""

    def __init__(self) -> None:
        """Initialize the CLI application."""
        self._network_manager = NetworkManager()
        self._pairing_manager: DevicePairingManager | None = None
        self._detected_coordinators: list[DetectedCoordinator] = []
        self._selected_coordinator: DetectedCoordinator | None = None
        self._running = True

    async def run(self) -> None:
        """Run the main CLI loop."""
        # Set up signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._signal_handler)

        ui.print_header("ZHA CLI - Zigbee Home Automation")

        # Run coordinator detection on entry
        await self._coordinator_entry_flow()

        try:
            while self._running:
                await self._main_menu()
        except KeyboardInterrupt:
            pass
        finally:
            await self._cleanup()

    async def _coordinator_entry_flow(self) -> None:
        """Handle coordinator detection and selection on entry."""
        while self._running and not self._selected_coordinator:
            await self._detect_coordinators_with_spinner()

            if not self._detected_coordinators:
                options = ["Retry detection", "Exit"]
                choice = ui.prompt_menu("No Coordinators Found", options)
                if choice == 0 or choice == 2:
                    self._running = False
                    return
                # choice == 1 means retry, loop continues
            else:
                await self._select_coordinator_menu()

    async def _detect_coordinators_with_spinner(self) -> None:
        """Detect coordinators with a loading spinner."""
        with ui.spinner("Detecting coordinators...") as progress:
            progress.add_task("Scanning serial ports for Zigbee coordinators...")
            try:
                self._detected_coordinators = await discover_coordinators()
            except Exception as exc:
                ui.print_error(f"Error detecting coordinators: {exc}")
                self._detected_coordinators = []

    async def _select_coordinator_menu(self) -> None:
        """Display coordinator selection menu."""
        ui.print_coordinators_table(self._detected_coordinators)

        if len(self._detected_coordinators) == 1:
            options = [
                f"Select {self._detected_coordinators[0].port}",
                "Retry detection",
                "Exit",
            ]
            choice = ui.prompt_menu("Coordinator Found", options)
            if choice == 0 or choice == 3:
                self._running = False
            elif choice == 1:
                self._selected_coordinator = self._detected_coordinators[0]
                ui.print_success(f"Selected: {self._selected_coordinator.port}")
            # choice == 2 means retry, will loop back
        else:
            # Multiple coordinators found
            options = [f"Select coordinator ({len(self._detected_coordinators)} found)"]
            options.append("Retry detection")
            options.append("Exit")
            choice = ui.prompt_menu("Coordinators Found", options)

            if choice == 0 or choice == 3:
                self._running = False
            elif choice == 1:
                coord_choice = ui.prompt_int(
                    "Select coordinator number",
                    default=1,
                )
                if 1 <= coord_choice <= len(self._detected_coordinators):
                    self._selected_coordinator = self._detected_coordinators[
                        coord_choice - 1
                    ]
                    ui.print_success(f"Selected: {self._selected_coordinator.port}")
            # choice == 2 means retry

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        self._running = False

    async def _cleanup(self) -> None:
        """Clean up resources."""
        ui.print_info("Shutting down...")
        await self._network_manager.shutdown()
        ui.print_success("Goodbye!")

    async def _main_menu(self) -> None:
        """Display and handle the main menu."""
        coordinator = self._selected_coordinator
        coord_info = f" ({coordinator.port})" if coordinator else ""

        options = [
            f"Start network{coord_info}",
            "Pair device",
            "List devices",
            "Control device",
            "Change coordinator",
            "Exit",
        ]

        if not self._network_manager.is_running:
            options[1] = "Pair device (start network first)"
            options[2] = "List devices (start network first)"
            options[3] = "Control device (start network first)"

        choice = ui.prompt_menu("Main Menu", options)

        if choice == 0:
            self._running = False
        elif choice == 1:
            await self._start_network()
        elif choice == 2:
            await self._pair_device()
        elif choice == 3:
            await self._list_devices()
        elif choice == 4:
            await self._control_device()
        elif choice == 5:
            self._selected_coordinator = None
            await self._coordinator_entry_flow()
        elif choice == 6:
            self._running = False

    async def _start_network(self) -> None:
        """Start the Zigbee network."""
        if self._network_manager.is_running:
            ui.print_warning("Network is already running")
            if ui.prompt_confirm("Restart network?", default=False):
                await self._network_manager.shutdown()
            else:
                return

        coordinator = self._selected_coordinator
        if coordinator is None:
            ui.print_error("No coordinator selected")
            return

        ui.print_header("Starting Network")
        ui.print_info(
            f"Connecting to {coordinator.radio_type.pretty_name} "
            f"at {coordinator.port}..."
        )

        try:
            gateway = await self._network_manager.start_network(coordinator)
            self._pairing_manager = DevicePairingManager(gateway)
            ui.print_success("Network started successfully!")

            # Show device count
            devices = self._network_manager.get_devices()
            ui.print_info(f"Found {len(devices)} paired device(s)")

        except Exception as exc:
            ui.print_error(f"Failed to start network: {exc}")
            _LOGGER.exception("Network start failed")

    async def _pair_device(self) -> None:
        """Enable pairing mode to add new devices."""
        if not self._network_manager.is_running:
            ui.print_error("Network is not running. Start the network first.")
            return

        ui.print_header("Device Pairing")

        duration = ui.prompt_int("Pairing duration (seconds)", default=60)

        ui.print_info(f"Enabling pairing mode for {duration} seconds...")
        ui.print_info("Put your Zigbee device in pairing mode now")

        if self._pairing_manager is None:
            ui.print_error("Pairing manager not initialized")
            return

        pairing_manager = self._pairing_manager

        try:
            await pairing_manager.enable_pairing(duration)

            # Set up event handlers to show progress
            def on_joined(event: Any) -> None:
                ui.print_info(f"Device joined: {event.device_info.ieee}")

            def on_initialized(event: Any) -> None:
                ui.print_success(
                    f"Device initialized: {event.device_info.manufacturer} "
                    f"{event.device_info.model}"
                )

            unsubscribe = pairing_manager.subscribe_to_events(
                on_joined=on_joined,
                on_initialized=on_initialized,
            )

            ui.print_info("Waiting for devices... (Press Ctrl+C to stop early)")

            try:
                await asyncio.sleep(duration)
            except asyncio.CancelledError:
                pass
            finally:
                unsubscribe()
                await pairing_manager.disable_pairing()

            ui.print_success("Pairing mode ended")

        except Exception as exc:
            ui.print_error(f"Pairing error: {exc}")
            _LOGGER.exception("Pairing failed")

    async def _list_devices(self) -> None:
        """List all paired devices."""
        if not self._network_manager.is_running:
            ui.print_error("Network is not running. Start the network first.")
            return

        ui.print_header("Paired Devices")

        devices = self._network_manager.get_devices()
        if not devices:
            ui.print_warning("No devices paired")
            return

        ui.print_devices_table(devices)

    async def _control_device(self) -> None:
        """Control a device."""
        if not self._network_manager.is_running:
            ui.print_error("Network is not running. Start the network first.")
            return

        ui.print_header("Device Control")

        # Get devices
        devices = self._network_manager.get_devices()
        if not devices:
            ui.print_warning("No devices paired")
            return

        # Show devices and select one
        ui.print_devices_table(devices)
        device_choice = ui.prompt_int("Select device number", default=1)

        if not (1 <= device_choice <= len(devices)):
            ui.print_error("Invalid selection")
            return

        selected_device = devices[device_choice - 1]["device"]

        # Get controllable entities
        entities = DeviceController.get_controllable_entities(selected_device)

        if not entities:
            ui.print_warning("No controllable entities found for this device")
            return

        # Show entities
        entity_infos = [DeviceController.get_entity_info(e) for e in entities]
        ui.print_entities_table(entity_infos)

        entity_choice = ui.prompt_int("Select entity number", default=1)

        if not (1 <= entity_choice <= len(entities)):
            ui.print_error("Invalid selection")
            return

        selected_entity = entities[entity_choice - 1]

        # Show control options
        control_options = ["Turn ON", "Turn OFF", "Toggle", "Back"]
        control_choice = ui.prompt_menu("Control Action", control_options)

        try:
            if control_choice == 1:
                await DeviceController.turn_on(selected_entity)
                ui.print_success("Device turned ON")
            elif control_choice == 2:
                await DeviceController.turn_off(selected_entity)
                ui.print_success("Device turned OFF")
            elif control_choice == 3:
                await DeviceController.toggle(selected_entity)
                ui.print_success("Device toggled")
        except Exception as exc:
            ui.print_error(f"Control error: {exc}")
            _LOGGER.exception("Control failed")


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the CLI."""
    level = logging.DEBUG if verbose else logging.WARNING

    # Set up basic logging
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Reduce noise from libraries
    logging.getLogger("zigpy").setLevel(logging.WARNING)
    logging.getLogger("bellows").setLevel(logging.WARNING)
    logging.getLogger("zigpy_znp").setLevel(logging.WARNING)
    logging.getLogger("zigpy_deconz").setLevel(logging.WARNING)
    logging.getLogger("zigpy_xbee").setLevel(logging.WARNING)
    logging.getLogger("zigpy_zigate").setLevel(logging.WARNING)


def main() -> None:
    """Run the ZHA CLI application."""
    parser = argparse.ArgumentParser(
        description="ZHA CLI - Zigbee Home Automation management tool"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    cli = ZHACli()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(cli.run())

    sys.exit(0)


if __name__ == "__main__":
    main()

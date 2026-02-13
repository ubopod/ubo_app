"""Network management for the Zigbee service."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from zha.application.gateway import Gateway
from zha.application.helpers import CoordinatorConfiguration, ZHAConfiguration, ZHAData

from ubo_app.logger import logger

if TYPE_CHECKING:
    from .coordinator_probe import DetectedCoordinator

# Default data directory for persistent storage
DEFAULT_DATA_DIR = Path.home() / '.zha-cli'


class NetworkManager:
    """Manages the Zigbee network lifecycle."""

    def __init__(self, data_dir: Path | None = None) -> None:
        """Initialize the network manager.

        Args:
            data_dir: Directory for persistent storage. Defaults to ~/.zha-cli

        """
        self._gateway: Gateway | None = None
        self._coordinator: DetectedCoordinator | None = None
        self._data_dir = data_dir or DEFAULT_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._device_names_cache: dict[str, str] | None = None
        self._device_locations_cache: dict[str, str] | None = None

    @property
    def gateway(self) -> Gateway | None:
        """Return the current gateway."""
        return self._gateway

    @property
    def coordinator(self) -> DetectedCoordinator | None:
        """Return the current coordinator."""
        return self._coordinator

    @property
    def is_running(self) -> bool:
        """Return True if the network is running."""
        return self._gateway is not None and not self._gateway.shutting_down

    def get_database_path(self, coordinator: DetectedCoordinator) -> Path:
        """Get the database path for a coordinator.

        Uses a hash of the port path to create a unique filename.
        This ensures devices persist when reconnecting to the same coordinator.
        """
        # Create a short hash from the port path for the filename
        port_hash = hashlib.md5(coordinator.port.encode()).hexdigest()[:12]  # noqa: S324
        # Use a readable name based on the port
        port_name = coordinator.port.replace('/', '_').replace('\\', '_')
        db_name = f'zigbee_{port_name}_{port_hash}.db'
        return self._data_dir / db_name

    def _get_coordinator_names_path(self) -> Path:
        """Get the path to the coordinator names file."""
        return self._data_dir / 'coordinator_names.json'

    def _load_coordinator_names(self) -> dict[str, str]:
        """Load coordinator names from file."""
        names_path = self._get_coordinator_names_path()
        if not names_path.exists():
            return {}
        try:
            return json.loads(names_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning('Failed to load coordinator names: %s', exc)
            return {}

    def _save_coordinator_names(self, names: dict[str, str]) -> None:
        """Save coordinator names to file."""
        names_path = self._get_coordinator_names_path()
        try:
            names_path.write_text(json.dumps(names, indent=2))
        except OSError as exc:
            logger.warning('Failed to save coordinator names: %s', exc)

    def get_coordinator_name(self, port: str) -> str | None:
        """Get the custom name for a coordinator by port."""
        names = self._load_coordinator_names()
        return names.get(port)

    def set_coordinator_name(self, port: str, name: str) -> None:
        """Set a custom name for a coordinator."""
        names = self._load_coordinator_names()
        names[port] = name
        self._save_coordinator_names(names)
        logger.info('Set coordinator name for %s: %s', port, name)

    def has_coordinator_name(self, port: str) -> bool:
        """Check if a coordinator has a custom name."""
        names = self._load_coordinator_names()
        return port in names

    def _get_names_path(self, coordinator: DetectedCoordinator) -> Path:
        """Get the device names file path for a coordinator."""
        db_path = self.get_database_path(coordinator)
        return db_path.with_suffix('.names.json')

    def _get_locations_path(self, coordinator: DetectedCoordinator) -> Path:
        """Get the device locations file path for a coordinator."""
        db_path = self.get_database_path(coordinator)
        return db_path.with_suffix('.locations.json')

    def _load_device_names(self) -> dict[str, str]:
        """Load device names from cache or disk.

        Uses in-memory cache to avoid repeated disk I/O.
        """
        if self._device_names_cache is not None:
            return self._device_names_cache

        if self._coordinator is None:
            return {}
        names_path = self._get_names_path(self._coordinator)
        if not names_path.exists():
            self._device_names_cache = {}
            return self._device_names_cache
        try:
            loaded: dict[str, str] = json.loads(names_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning('Failed to load device names: %s', exc)
            self._device_names_cache = {}
            return self._device_names_cache
        else:
            self._device_names_cache = loaded
            return loaded

    def _save_device_names(self, names: dict[str, str]) -> None:
        """Save device names to the current coordinator's names file."""
        if self._coordinator is None:
            return
        names_path = self._get_names_path(self._coordinator)
        try:
            names_path.write_text(json.dumps(names, indent=2))
        except OSError as exc:
            logger.warning('Failed to save device names: %s', exc)

    def set_device_name(self, ieee: str, name: str) -> None:
        """Set a custom name for a device."""
        names = self._load_device_names()
        names[str(ieee)] = name
        self._device_names_cache = names  # Update cache
        self._save_device_names(names)
        logger.info('Set device name for %s: %s', ieee, name)

    def _load_device_locations(self) -> dict[str, str]:
        """Load device locations from cache or disk.

        Uses in-memory cache to avoid repeated disk I/O.
        """
        if self._device_locations_cache is not None:
            return self._device_locations_cache

        if self._coordinator is None:
            return {}
        locations_path = self._get_locations_path(self._coordinator)
        if not locations_path.exists():
            self._device_locations_cache = {}
            return self._device_locations_cache
        try:
            loaded: dict[str, str] = json.loads(locations_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning('Failed to load device locations: %s', exc)
            self._device_locations_cache = {}
            return self._device_locations_cache
        else:
            self._device_locations_cache = loaded
            return loaded

    def _save_device_locations(self, locations: dict[str, str]) -> None:
        """Save device locations to the current coordinator's locations file."""
        if self._coordinator is None:
            return
        locations_path = self._get_locations_path(self._coordinator)
        try:
            locations_path.write_text(json.dumps(locations, indent=2))
        except OSError as exc:
            logger.warning('Failed to save device locations: %s', exc)

    def set_device_location(self, ieee: str, location: str) -> None:
        """Set a custom location for a device."""
        locations = self._load_device_locations()
        locations[str(ieee)] = location
        self._device_locations_cache = locations  # Update cache
        self._save_device_locations(locations)
        logger.info('Set device location for %s: %s', ieee, location)

    def has_existing_network(self, coordinator: DetectedCoordinator) -> bool:
        """Check if a coordinator has an existing network database.

        Returns:
            True if a database file exists for this coordinator.

        """
        db_path = self.get_database_path(coordinator)
        return db_path.exists() and db_path.stat().st_size > 0

    async def start_network(self, coordinator: DetectedCoordinator) -> Gateway:
        """Start the Zigbee network with the specified coordinator.

        Creates a ZHAData configuration and initializes the gateway.

        Args:
            coordinator: The detected coordinator to use.

        Returns:
            The initialized Gateway instance.

        Raises:
            Exception: If the gateway fails to initialize.

        """
        if self._gateway is not None:
            logger.warning('Network already running, shutting down first')
            await self.shutdown()

        # Get persistent database path for this coordinator
        db_path = self.get_database_path(coordinator)

        logger.info(
            'Starting network with %s at %s (%d baud), database: %s',
            coordinator.radio_type.pretty_name,
            coordinator.port,
            coordinator.baudrate,
            db_path,
        )

        # Create the configuration with persistent database
        coordinator_config = CoordinatorConfiguration(
            path=coordinator.port,
            baudrate=coordinator.baudrate,
            radio_type=coordinator.radio_type.name,
        )

        zha_config = ZHAConfiguration(
            coordinator_configuration=coordinator_config,
        )

        # Pass database path through zigpy_config
        # Disable network validation — after a reset the radio has new settings
        # that don't match the old backup in the database, which is expected.
        zigpy_config = {
            'database_path': str(db_path),
            'validate_network_settings': False,
        }

        zha_data = ZHAData(config=zha_config, zigpy_config=zigpy_config)

        # Create and initialize the gateway
        self._gateway = await Gateway.async_from_config(zha_data)
        await self._gateway.async_initialize()

        self._coordinator = coordinator
        self._device_names_cache = None  # Invalidate cache on coordinator change
        self._device_locations_cache = None

        logger.info('Network started successfully')
        return self._gateway

    async def shutdown(self) -> None:
        """Shut down the Zigbee network."""
        if self._gateway is None:
            logger.debug('No network to shut down')
            return

        logger.info('Shutting down network')
        try:
            await self._gateway.shutdown()
        except Exception:  # noqa: BLE001
            logger.warning(
                'Error during network shutdown, forcing cleanup',
                exc_info=True,
            )
        self._gateway = None
        self._coordinator = None
        logger.info('Network shut down successfully')

    async def reset(self, coordinator: DetectedCoordinator | None = None) -> None:
        """Reset the network completely, deleting all persistent data.

        This resets the coordinator hardware, shuts down the network, and
        deletes the database file, removing all paired devices and network
        configuration.

        Args:
            coordinator: The coordinator to reset. If None, uses current coordinator.

        """
        coord = coordinator or self._coordinator
        if coord is None:
            logger.warning('No coordinator specified for reset')
            return

        # Reset coordinator hardware BEFORE shutting down (requires active gateway)
        if self._gateway is not None:
            try:
                await self._gateway.application_controller.reset_network_info()
            except Exception:  # noqa: BLE001
                logger.warning('Failed to reset coordinator hardware', exc_info=True)

        # Shut down and delete database
        if self._gateway is not None:
            await self.shutdown()

        # Delete the database file
        db_path = self.get_database_path(coord)
        self._delete_database_file(db_path)

    def _delete_database_file(self, db_path: Path) -> None:
        """Delete a database file and its related files."""
        if db_path.exists():
            logger.info('Deleting network database: %s', db_path)
            try:
                db_path.unlink()
            except OSError as exc:
                logger.warning('Failed to delete database %s: %s', db_path, exc)
                return

            # Also delete any related files (e.g., -wal, -shm for SQLite)
            for suffix in ['-wal', '-shm', '-journal']:
                related = db_path.with_suffix(db_path.suffix + suffix)
                if related.exists():
                    try:
                        related.unlink()
                    except OSError as exc:
                        logger.warning('Failed to delete %s: %s', related, exc)

            logger.info('Network database deleted')

        # Delete the device names file
        names_path = db_path.with_suffix('.names.json')
        if names_path.exists():
            logger.info('Deleting device names: %s', names_path)
            try:
                names_path.unlink()
            except OSError as exc:
                logger.warning('Failed to delete device names %s: %s', names_path, exc)

        # Delete the device locations file
        locations_path = db_path.with_suffix('.locations.json')
        if locations_path.exists():
            logger.info('Deleting device locations: %s', locations_path)
            try:
                locations_path.unlink()
            except OSError as exc:
                logger.warning(
                    'Failed to delete device locations %s: %s',
                    locations_path,
                    exc,
                )

    def delete_all_networks(self) -> int:
        """Delete all saved network databases.

        Returns:
            Number of database files deleted.

        """
        deleted = 0
        for db_file in self._data_dir.glob('zigbee_*.db'):
            logger.info('Deleting: %s', db_file)
            self._delete_database_file(db_file)
            deleted += 1
        return deleted

    def get_saved_network_count(self) -> int:
        """Get the number of saved network databases."""
        return len(list(self._data_dir.glob('zigbee_*.db')))

    def get_devices(self) -> list[dict]:
        """Get all paired devices.

        Returns:
            List of device info dictionaries with custom names if set.

        """
        if self._gateway is None:
            return []

        custom_names = self._load_device_names()
        custom_locations = self._load_device_locations()
        devices = []
        for device in self._gateway.devices.values():
            # Skip the coordinator
            if device.is_coordinator:
                continue

            ieee_str = str(device.ieee)
            custom_name = custom_names.get(ieee_str)

            devices.append(
                {
                    'ieee': device.ieee,
                    'nwk': device.nwk,
                    'manufacturer': device.manufacturer,
                    'model': device.model,
                    'name': custom_name or device.name,
                    'custom_name': custom_name,
                    'location': custom_locations.get(ieee_str),
                    'available': device.available,
                    'device': device,
                },
            )

        return devices

    def get_device_by_ieee(self, ieee: str) -> dict | None:
        """Get a fresh device reference by IEEE address.

        Args:
            ieee: The IEEE address of the device.

        Returns:
            Device info dictionary or None if not found.

        """
        if self._gateway is None:
            return None

        custom_names = self._load_device_names()
        custom_locations = self._load_device_locations()

        # Convert string IEEE to the format used by the gateway
        for device in self._gateway.devices.values():
            if str(device.ieee) == str(ieee):
                ieee_str = str(device.ieee)
                custom_name = custom_names.get(ieee_str)
                return {
                    'ieee': device.ieee,
                    'nwk': device.nwk,
                    'manufacturer': device.manufacturer,
                    'model': device.model,
                    'name': custom_name or device.name,
                    'custom_name': custom_name,
                    'location': custom_locations.get(ieee_str),
                    'available': device.available,
                    'device': device,
                }

        return None

    async def remove_device(self, ieee: str) -> bool:
        """Remove a device from the network.

        Args:
            ieee: The IEEE address of the device to remove.

        Returns:
            True if device was removed successfully, False otherwise.

        """
        if self._gateway is None:
            return False

        # Find the device
        device = None
        for dev in self._gateway.devices.values():
            if str(dev.ieee) == str(ieee):
                device = dev
                break

        if device is None:
            logger.warning('Device %s not found for removal', ieee)
            return False

        try:
            # Remove from the Zigbee network
            await self._gateway.application_controller.remove(device.ieee)
            logger.info('Device %s removed from network', ieee)

            # Remove custom name if exists
            names = self._load_device_names()
            if str(ieee) in names:
                del names[str(ieee)]
                self._save_device_names(names)

            # Remove custom location if exists
            locations = self._load_device_locations()
            if str(ieee) in locations:
                del locations[str(ieee)]
                self._save_device_locations(locations)
        except Exception:
            logger.exception('Failed to remove device %s', ieee)
            return False
        else:
            return True

    def get_backups(self) -> list[dict]:
        """Get all backups for the current network.

        Returns:
            List of dicts with: index, backup_time, device_count, is_complete

        """
        if self._gateway is None:
            return []

        backups = self._gateway.application_controller.backups.backups
        result = []
        for i, backup in enumerate(backups):
            device_count = (
                len(backup.network_info.nwk_addresses) if backup.network_info else 0
            )
            result.append(
                {
                    'index': i,
                    'backup_time': backup.backup_time.strftime('%Y-%m-%d %H:%M')
                    if backup.backup_time
                    else 'Unknown',
                    'device_count': device_count,
                    'is_complete': backup.is_complete(),
                },
            )
        return result

    async def create_backup(self) -> dict | None:
        """Create a new backup of current network state.

        Returns:
            Info about the created backup, or None if failed.

        """
        if self._gateway is None:
            return None

        backup = await self._gateway.application_controller.backups.create_backup()
        device_count = (
            len(backup.network_info.nwk_addresses) if backup.network_info else 0
        )
        return {
            'backup_time': backup.backup_time.strftime('%Y-%m-%d %H:%M')
            if backup.backup_time
            else 'Unknown',
            'device_count': device_count,
            'is_complete': backup.is_complete(),
        }

    async def restore_backup(self, index: int) -> None:
        """Restore network from a specific backup.

        Args:
            index: The backup index to restore.

        Raises:
            RuntimeError: If network is not running.
            ValueError: If backup index is invalid.

        """
        if self._gateway is None:
            msg = 'Network not running'
            raise RuntimeError(msg)

        backups = self._gateway.application_controller.backups.backups
        if index < 0 or index >= len(backups):
            msg = 'Invalid backup index'
            raise ValueError(msg)

        backup = backups[index]
        await self._gateway.application_controller.backups.restore_backup(backup)

    def delete_backup(self, index: int) -> None:
        """Delete a backup by index.

        Args:
            index: The backup index to delete.

        Raises:
            RuntimeError: If network is not running.
            ValueError: If backup index is invalid.

        """
        if self._gateway is None:
            msg = 'Network not running'
            raise RuntimeError(msg)

        backups = self._gateway.application_controller.backups.backups
        if index < 0 or index >= len(backups):
            msg = 'Invalid backup index'
            raise ValueError(msg)

        backup = backups[index]
        self._gateway.application_controller.backups.backups.remove(backup)

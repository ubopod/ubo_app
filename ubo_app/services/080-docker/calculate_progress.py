"""Docker image pull progress calculation utilities."""

from __future__ import annotations

import re
import time
from typing import TypedDict

from ubo_app.logger import logger

# Type alias for service tracker dictionary
ServiceTrackers = dict[str, 'LayerProgressTracker']


class DockerLayerStatus:
    """Docker layer status constants."""

    ALREADY_EXISTS = 'Already exists'
    PULL_COMPLETE = 'Pull complete'
    DOWNLOAD_COMPLETE = 'Download complete'
    DOWNLOADING = 'Downloading'
    EXTRACTING = 'Extracting'
    WAITING = 'Waiting'
    PULLING_FS_LAYER = 'Pulling fs layer'

    # Groupings for convenience
    COMPLETED_STATUSES = (ALREADY_EXISTS, PULL_COMPLETE, DOWNLOAD_COMPLETE)


def parse_byte_size(size_str: str) -> int | None:
    """Parse size string like '23.4MB' to bytes.

    Returns None if parsing fails.
    """
    try:
        size_str = size_str.strip()
        match = re.match(r'([0-9.]+)\s*([KMGT]?B)', size_str, re.IGNORECASE)
        if not match:
            return None

        value = float(match.group(1))
        unit = match.group(2).upper()

        multipliers = {
            'B': 1,
            'KB': 1024,
            'MB': 1024 ** 2,
            'GB': 1024 ** 3,
            'TB': 1024 ** 4,
        }

        return int(value * multipliers.get(unit, 1))
    except (ValueError, AttributeError):
        return None


def parse_progress_string(progress_str: str) -> tuple[int, int] | None:
    """Parse progress string like '23.4MB/100MB' or '[==> ] 23.4MB/100MB'.

    Returns (downloaded_bytes, total_bytes) or None if parsing fails.
    """
    try:
        # Remove progress bar indicators like '[==> ]'
        progress_str = re.sub(r'\[.*?\]\s*', '', progress_str)

        # Match pattern like '23.4MB/100MB'
        match = re.match(
            r'([0-9.]+\s*[KMGT]?B)\s*/\s*([0-9.]+\s*[KMGT]?B)',
            progress_str.strip(),
            re.IGNORECASE,
        )

        if not match:
            return None

        downloaded = parse_byte_size(match.group(1))
        total = parse_byte_size(match.group(2))

        if downloaded is None or total is None or total == 0:
            return None

    except (ValueError, AttributeError):
        return None
    else:
        return (downloaded, total)


class LayerData(TypedDict):
    """Type definition for layer progress data."""

    status: str
    downloaded: int
    total: int


class LayerProgressTracker:
    """Track progress of Docker image pull with hybrid byte/layer-based approach."""

    def __init__(self, image_id: str) -> None:
        """Initialize the tracker."""
        self.image_id = image_id
        self.layers: dict[str, LayerData] = {}
        self.last_update_time = 0.0
        self.update_interval = 1.0  # 1 second debounce

    def update_layer(self, layer_id: str, status: str, progress: str = '') -> None:
        """Update layer status and progress.

        Protects completed layers from regressing to incomplete states.
        """
        if layer_id == 'unknown':
            return

        if layer_id not in self.layers:
            self.layers[layer_id] = {
                'status': status,
                'downloaded': 0,
                'total': 0,
            }
        else:
            # Don't allow completed layers to regress
            current_status = self.layers[layer_id]['status']
            if current_status in DockerLayerStatus.COMPLETED_STATUSES:
                # Layer is already complete, don't update status
                return

        self.layers[layer_id]['status'] = status

        # Try to parse byte progress
        if progress:
            parsed = parse_progress_string(progress)
            if parsed:
                downloaded, total = parsed
                self.layers[layer_id]['downloaded'] = downloaded
                self.layers[layer_id]['total'] = total

    def mark_all_complete(self) -> None:
        """Mark all layers as complete (used when service completes)."""
        for layer_data in self.layers.values():
            layer_data['status'] = DockerLayerStatus.PULL_COMPLETE

    def calculate_layer_based_progress(self) -> float:
        """Calculate progress with layer-count weighting (monotonic).

        Each layer contributes equally (1/N) to total progress.
        Within each layer, progress is calculated from bytes downloaded.

        Example: 5 layers, 2 complete, 3rd at 50% downloaded:
        - Layer 1: 100% → contributes 1.0
        - Layer 2: 100% → contributes 1.0
        - Layer 3: 50% → contributes 0.5
        - Layer 4: 0% → contributes 0.0
        - Layer 5: 0% → contributes 0.0
        - Total: (1.0 + 1.0 + 0.5 + 0.0 + 0.0) / 5 = 50%

        Returns:
            Progress as a value between 0 and 1.

        """
        if not self.layers:
            return 0.0

        total_layer_progress = 0.0

        for layer_data in self.layers.values():
            status = layer_data.get('status', '')

            # Fully complete layers contribute 1.0
            if status in DockerLayerStatus.COMPLETED_STATUSES:
                total_layer_progress += 1.0
            # In-progress layers contribute based on bytes downloaded
            elif status == DockerLayerStatus.DOWNLOADING:
                downloaded = layer_data.get('downloaded', 0)
                total = layer_data.get('total', 0)
                if total > 0:
                    # Byte-based progress for this layer
                    layer_progress = downloaded / total
                    total_layer_progress += layer_progress
                # else: no byte info yet, contributes 0.0
            # Other statuses (Waiting, Pulling fs layer, etc.) contribute 0.0

        total_layers = len(self.layers)
        return total_layer_progress / total_layers if total_layers > 0 else 0.0

    def calculate_progress(self) -> float:
        """Calculate overall progress as a value between 0 and 1.

        Uses byte-based calculation when available, falls back to layer counting.

        DEPRECATED: Use calculate_layer_based_progress() for monotonic progress.
        """
        if not self.layers:
            return 0.0

        # Try byte-based calculation first
        total_bytes = 0
        downloaded_bytes = 0
        layers_with_bytes = 0

        for layer_data in self.layers.values():
            total = layer_data.get('total', 0)
            if isinstance(total, int) and total > 0:
                layers_with_bytes += 1
                total_bytes += total
                downloaded_bytes += layer_data.get('downloaded', 0) or 0

        # If we have byte information for at least some layers, use it
        if layers_with_bytes > 0 and total_bytes > 0:
            return min(downloaded_bytes / total_bytes, 1.0)

        # Fall back to layer-based calculation
        layer_weights = {
            DockerLayerStatus.ALREADY_EXISTS: 1.0,
            DockerLayerStatus.PULL_COMPLETE: 1.0,
            DockerLayerStatus.DOWNLOAD_COMPLETE: 0.9,
            DockerLayerStatus.EXTRACTING: 0.7,
            DockerLayerStatus.DOWNLOADING: 0.3,
            DockerLayerStatus.WAITING: 0.1,
            DockerLayerStatus.PULLING_FS_LAYER: 0.0,
        }

        total_progress = 0.0
        for layer_data in self.layers.values():
            status = layer_data.get('status', '')
            total_progress += layer_weights.get(status, 0.0)

        return min(total_progress / len(self.layers), 1.0) if self.layers else 0.0

    def should_update_ui(self) -> bool:
        """Check if enough time has passed to update UI (debouncing)."""
        current_time = time.time()
        if current_time - self.last_update_time >= self.update_interval:
            self.last_update_time = current_time
            return True
        return False

    def cleanup(self) -> None:
        """Clean up layer data to free memory.

        Call this when the tracker is no longer needed to help garbage collection.
        """
        self.layers.clear()
        self.last_update_time = 0.0


def calculate_layer_progress(layer_data: LayerData) -> float:
    """Calculate progress contribution for a single layer.

    Args:
        layer_data: Dictionary containing layer status and progress info

    Returns:
        Progress value between 0.0 and 1.0 for this layer

    """
    status = layer_data.get('status', '')

    # Fully complete layers contribute 1.0
    if status in DockerLayerStatus.COMPLETED_STATUSES:
        return 1.0

    # In-progress layers contribute based on bytes downloaded
    if status == DockerLayerStatus.DOWNLOADING:
        downloaded = layer_data.get('downloaded', 0)
        total = layer_data.get('total', 0)
        if total > 0:
            return downloaded / total
        return 0.0

    # Extracting layers should count as mostly complete
    if status == DockerLayerStatus.EXTRACTING:
        downloaded = layer_data.get('downloaded', 0)
        total = layer_data.get('total', 0)
        if total > 0:
            return max(downloaded / total, 0.9)
        return 0.9

    # Other statuses contribute 0.0
    return 0.0


def calculate_composition_progress(
    service_trackers: ServiceTrackers,
    completed_services: set[str],
    total_count: int,
) -> float:
    """Calculate overall progress using service-segmented approach.

    Each service owns an equal portion of the progress bar (1/total_count).
    Within each service's portion, progress is calculated based on its announced layers.

    Example with 4 services:
    - Service 1 (database): 0-25% based on its layers
    - Service 2 (immich-server): 25-50% based on its layers
    - Service 3 (redis): 50-75% based on its layers
    - Service 4 (immich-machine-learning): 75-100% based on its layers

    This prevents premature 100% completion when only some services have started.

    Args:
        service_trackers: Dict of LayerProgressTracker for each service
        completed_services: Set of completed service names
        total_count: Total number of services expected

    Returns:
        Overall progress as float between 0.0 and 1.0

    """
    if total_count <= 0:
        return 0.0

    # Each service gets an equal portion of the progress bar
    service_portion = 1.0 / total_count
    total_progress = 0.0

    # Track per-service stats for logging
    service_stats = {}
    for service_name, tracker in service_trackers.items():
        # If service is marked complete, force it to contribute full portion
        if service_name in completed_services:
            service_progress = 1.0
            service_stats[service_name] = {
                'total_layers': len(tracker.layers),
                'service_progress': 1.0,
                'is_complete': True,
                'forced_complete': True,
            }
        else:
            service_layers = tracker.layers.values()
            if not service_layers:
                # Service has no announced layers yet, contributes 0.0
                service_progress = 0.0
            else:
                # Calculate progress within this service based on its layers
                service_layer_progress = 0.0
                completed_count = 0
                downloading_count = 0
                extracting_count = 0

                for layer_data in service_layers:
                    layer_progress = calculate_layer_progress(layer_data)
                    service_layer_progress += layer_progress

                    # Update counters for stats
                    status = layer_data.get('status', '')
                    if status in DockerLayerStatus.COMPLETED_STATUSES:
                        completed_count += 1
                    elif status == DockerLayerStatus.DOWNLOADING:
                        downloading_count += 1
                    elif status == DockerLayerStatus.EXTRACTING:
                        extracting_count += 1

                # Service progress is normalized by its layer count
                total_service_layers = len(service_layers)
                service_progress = (service_layer_progress / total_service_layers
                                  if total_service_layers > 0 else 0.0)

                service_stats[service_name] = {
                    'total_layers': total_service_layers,
                    'completed': completed_count,
                    'downloading': downloading_count,
                    'extracting': extracting_count,
                    'service_progress': service_progress,
                    'is_complete': False,
                }

        # Add this service's contribution (its progress * its portion)
        total_progress += service_progress * service_portion

    logger.debug('Calculating progress', extra={
        'total_services': total_count,
        'tracked_services': len(service_trackers),
        'completed_services': len(completed_services),
        'service_portion': service_portion,
        'service_stats': service_stats,
        'total_progress': total_progress,
    })

    return min(total_progress, 1.0)


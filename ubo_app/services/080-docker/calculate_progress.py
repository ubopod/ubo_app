"""Docker image pull progress calculation utilities."""

from __future__ import annotations

import re
import time
from typing import TypedDict


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
        """Update layer status and progress."""
        if layer_id == 'unknown':
            return

        if layer_id not in self.layers:
            self.layers[layer_id] = {
                'status': status,
                'downloaded': 0,
                'total': 0,
            }

        self.layers[layer_id]['status'] = status

        # Try to parse byte progress
        if progress:
            parsed = parse_progress_string(progress)
            if parsed:
                downloaded, total = parsed
                self.layers[layer_id]['downloaded'] = downloaded
                self.layers[layer_id]['total'] = total

    def calculate_progress(self) -> float:
        """Calculate overall progress as a value between 0 and 1.

        Uses byte-based calculation when available, falls back to layer counting.
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
            'Already exists': 1.0,
            'Pull complete': 1.0,
            'Download complete': 0.9,
            'Extracting': 0.7,
            'Downloading': 0.3,
            'Waiting': 0.1,
            'Pulling fs layer': 0.0,
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

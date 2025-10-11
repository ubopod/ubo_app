# ruff: noqa: D100
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


class CameraBackend(Protocol):
    """Protocol defining the interface for camera backends."""

    def start(self) -> None:
        """Start the camera."""
        ...

    def stop(self) -> None:
        """Stop the camera."""
        ...

    def close(self) -> None:
        """Release camera resources."""
        ...

    def capture_array(self, stream: str = 'main') -> NDArray[np.uint8] | None:
        """Capture a frame from the camera as a numpy array.

        Args:
            stream: The stream name (for compatibility with PiCamera2)

        Returns:
            Numpy array containing the frame data in RGB format, or None if
            capture fails

        """
        ...

    def configure(self, config: dict | str) -> None:
        """Configure the camera with the given configuration.

        Args:
            config: Configuration dictionary or string

        """
        ...

    def set_controls(self, controls: dict) -> None:
        """Set camera controls.

        Args:
            controls: Dictionary of control parameters

        """
        ...

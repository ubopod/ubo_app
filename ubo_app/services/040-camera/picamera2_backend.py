# ruff: noqa: D100
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from picamera2.picamera2 import Picamera2

from ubo_app.logger import logger

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


class PiCamera2Backend:
    """Camera backend implementation using PiCamera2 for Raspberry Pi."""

    def __init__(self, width: int, height: int, camera_index: int = 0) -> None:
        """Initialize the PiCamera2 backend.

        Args:
            width: Desired frame width
            height: Desired frame height
            camera_index: Camera device index (default: 0)

        """
        self._picamera2: Picamera2 | None = None
        self._width = width
        self._height = height
        self._camera_index = camera_index
        self._initialize()

    def _initialize(self) -> None:
        """Initialize the PiCamera2 instance."""
        try:
            self._picamera2 = Picamera2(self._camera_index)
            preview_config = cast(
                'str',
                self._picamera2.create_still_configuration(
                    {
                        'format': 'RGB888',
                        'size': (self._width, self._height),
                    },
                ),
            )
            self._picamera2.configure(preview_config)
            try:
                self._picamera2.set_controls({'AwbEnable': True})
            except Exception:
                logger.exception('Failed to set camera controls.')
        except IndexError:
            logger.exception('Camera not found.')
            self._picamera2 = None

    def start(self) -> None:
        """Start the camera."""
        if self._picamera2:
            self._picamera2.start()

    def stop(self) -> None:
        """Stop the camera."""
        if self._picamera2:
            self._picamera2.stop()

    def close(self) -> None:
        """Release camera resources."""
        if self._picamera2:
            self._picamera2.close()

    def capture_array(self, stream: str = 'main') -> NDArray[np.uint8] | None:
        """Capture a frame from the camera.

        Args:
            stream: The stream name to capture from

        Returns:
            Numpy array containing the frame data in RGB format

        """
        if self._picamera2:
            return self._picamera2.capture_array(stream)
        return None

    def configure(self, config: dict | str) -> None:
        """Configure the camera.

        Args:
            config: Configuration dictionary or string

        """
        if self._picamera2:
            self._picamera2.configure(config)

    def set_controls(self, controls: dict) -> None:
        """Set camera controls.

        Args:
            controls: Dictionary of control parameters

        """
        if self._picamera2:
            self._picamera2.set_controls(controls)

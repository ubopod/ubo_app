# ruff: noqa: D100
from __future__ import annotations

from typing import TYPE_CHECKING

from picamera2.picamera2 import Picamera2

from ubo_app.logger import logger

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

# libcamera's `controls.AfModeEnum.Continuous`. Spelled out rather than
# imported from `libcamera` because there is no stub for it under `typings/`;
# the value is part of libcamera's published control definitions.
AF_MODE_CONTINUOUS = 2


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
            # A *preview* configuration keeps the sensor in a binned,
            # high-frame-rate mode. A still configuration selects the
            # full-resolution, low-frame-rate mode instead, which both starves
            # the viewfinder's `VIEWFINDER_INTERVAL` feed loop and leaves
            # continuous autofocus too few frames to converge on.
            self._picamera2.configure(
                self._picamera2.create_preview_configuration(
                    {
                        'format': 'RGB888',
                        'size': (self._width, self._height),
                    },
                ),
            )
            self._apply_default_controls()
        except IndexError:
            logger.exception('Camera not found.')
            self._picamera2 = None

    def _apply_default_controls(self) -> None:
        """Enable auto white balance and, if the lens moves, continuous focus.

        Focus support is probed from the controls the opened camera advertises
        rather than from a persisted camera-type flag: every module with a
        movable lens exposes `AfMode`, so the Pi Camera Module 3 (IMX708), an
        Arducam IMX519 with its VCM enabled, and any future autofocus module
        all light up without configuration. Fixed-focus hardware (IMX219,
        `imx519,vcm=off`, USB webcams) doesn't advertise it and is skipped, so
        `set_controls` is never asked for a control the camera can't honour.
        """
        if not self._picamera2:
            return

        controls: dict[str, object] = {'AwbEnable': True}
        if 'AfMode' in self._picamera2.camera_controls:
            controls['AfMode'] = AF_MODE_CONTINUOUS

        try:
            self._picamera2.set_controls(controls)
        except Exception:
            logger.exception('Failed to set camera controls.')

    def start(self) -> None:
        """Start the camera."""
        if self._picamera2:
            self._picamera2.start()
            # `configure()` rebuilds the control set from the configuration,
            # dropping anything set beforehand. The viewfinder session rebuilds
            # this backend whenever the selected source changes, so re-assert
            # the controls on every start to keep autofocus running.
            self._apply_default_controls()

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

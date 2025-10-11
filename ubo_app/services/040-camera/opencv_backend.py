# ruff: noqa: D100
from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.logger import logger

if TYPE_CHECKING:
    import cv2
    import numpy as np
    from numpy._typing._array_like import NDArray


class OpenCVCameraBackend:
    """Camera backend implementation using OpenCV for macOS/Linux."""

    def __init__(self, width: int, height: int, camera_index: int) -> None:
        """Initialize the OpenCV camera backend.

        Args:
            width: Desired frame width
            height: Desired frame height
            camera_index: Camera device index

        """
        self._width = width
        self._height = height
        self._camera_index = camera_index
        self._capture: cv2.VideoCapture | None = None
        self._initialize()

    def _initialize(self) -> None:
        """Initialize the OpenCV VideoCapture."""
        try:
            import cv2

            self._capture = cv2.VideoCapture(self._camera_index)

            if not self._capture.isOpened():
                logger.error('Failed to open camera at index %d', self._camera_index)
                self._capture = None
                return

            # Set camera properties
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)

            # Verify camera is working by capturing a test frame
            ret, _ = self._capture.read()
            if not ret:
                logger.error('Camera opened but failed to capture test frame')
                self._capture.release()
                self._capture = None
                return

            logger.info(
                'OpenCV camera initialized successfully (index: %d, resolution: %dx%d)',
                self._camera_index,
                self._width,
                self._height,
            )
        except Exception:
            logger.exception('Failed to initialize OpenCV camera')
            self._capture = None

    def start(self) -> None:
        """Start the camera and allow time for auto-exposure adjustment."""
        if self._capture is None:
            self._initialize()

        # Warm-up: Capture and discard frames to allow camera auto-exposure
        # to adjust, especially important in low-light conditions
        if self._capture:
            import time

            logger.info('Warming up camera for auto-exposure adjustment...')
            for _ in range(3):
                self._capture.read()
                time.sleep(0.1)  # 100ms between frames
            logger.info('Camera warm-up complete')

    def stop(self) -> None:
        """Stop the camera (no-op for OpenCV, use close() to release)."""

    def close(self) -> None:
        """Release camera resources."""
        if self._capture:
            self._capture.release()
            self._capture = None

    def capture_array(self, stream: str = 'main') -> NDArray[np.uint8] | None:
        """Capture a frame from the camera.

        Args:
            stream: Ignored for OpenCV (for compatibility with PiCamera2)

        Returns:
            Numpy array containing the frame data in RGB format, or None if
            capture fails

        """
        _ = stream  # Unused but required for protocol compatibility
        if not self._capture:
            return None

        import cv2
        import numpy as np

        ret, frame = self._capture.read()

        if not ret or frame is None:
            logger.warning('Failed to capture frame from camera')
            return None

        # Convert BGR (OpenCV default) to RGB (expected by the rest of the code)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Rotate 180 degrees to correct upside-down orientation
        frame_rgb = cv2.rotate(frame_rgb, cv2.ROTATE_180)

        # Resize if needed to match expected dimensions
        if frame_rgb.shape[0] != self._height or frame_rgb.shape[1] != self._width:
            frame_rgb = cv2.resize(
                frame_rgb,
                (self._width, self._height),
                interpolation=cv2.INTER_LINEAR,
            )

        return frame_rgb.astype(np.uint8)

    def configure(self, config: dict | str) -> None:
        """Configure the camera.

        Args:
            config: Configuration dictionary (ignored for OpenCV)

        """
        # OpenCV doesn't support complex configuration like PiCamera2
        # This is a no-op for compatibility

    def set_controls(self, controls: dict) -> None:
        """Set camera controls.

        Args:
            controls: Dictionary of control parameters (ignored for OpenCV)

        """
        # OpenCV has limited control options compared to PiCamera2
        # This is a no-op for compatibility

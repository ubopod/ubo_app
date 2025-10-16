"""Utility functions for camera service."""

from __future__ import annotations

from ubo_app.logger import logger


def detect_available_cameras_picamera2() -> list[int]:
    """Detect available Picamera2 cameras on Raspberry Pi.

    Returns:
        List of working camera indices

    """
    try:
        from picamera2.picamera2 import Picamera2

        available = []
        logger.info('Detecting available Picamera2 cameras...')

        # Get list of available cameras
        cameras = Picamera2.global_camera_info()

        for i, camera_info in enumerate(cameras):
            logger.info(
                'Found camera at index {index}: {info}',
                extra={'index': i, 'info': camera_info},
            )
            available.append(i)

        logger.info(
            'Picamera2 detection complete: {count} camera(s) found',
            extra={'count': len(available), 'indices': available},
        )
    except (ImportError, RuntimeError, OSError) as e:
        logger.exception(
            'Failed to detect Picamera2 cameras',
            extra={'error': e},
        )
    else:
        return available

    return []


def detect_available_cameras(max_index: int = 10) -> list[int]:
    """Detect available camera indices by attempting to open them.

    Args:
        max_index: Maximum camera index to check (default: 10)

    Returns:
        List of working camera indices

    """
    import cv2

    available = []
    logger.info('Detecting available cameras...')

    for i in range(max_index):
        cap = None
        try:
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                # Try to read a frame to verify camera actually works
                ret, frame = cap.read()
                if ret and frame is not None:
                    available.append(i)
                    logger.info(
                        'Found working camera at index {index}',
                        extra={'index': i},
                    )
        except (cv2.error, OSError, RuntimeError) as e:
            logger.debug(
                'Failed to open camera at index {index}',
                extra={'index': i, 'error': e},
            )
        finally:
            if cap is not None:
                cap.release()

    logger.info(
        'Camera detection complete: {count} camera(s) found',
        extra={'count': len(available), 'indices': available},
    )
    return available

# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import numpy as np
from headless_kivy_pi import HeadlessWidget
from kivy import re
from kivy.clock import Clock

from ubo_app.logging import logger
from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.camera import (
    CameraBarcodeAction,
    CameraStartViewfinderEvent,
    CameraStopViewfinderEvent,
)

if TYPE_CHECKING:
    from numpy._typing import NDArray

THROTTL_TIME = 0.5


def resize_image(
    image: NDArray[np.uint8],
    new_size: tuple[int, int] = (HeadlessWidget.width, HeadlessWidget.height),
) -> NDArray[np.uint8]:
    scale_x = image.shape[1] / new_size[1]
    scale_y = image.shape[0] / new_size[0]

    # Use slicing to downsample the image
    resized = image[:: int(scale_y), :: int(scale_x)]

    # Handle any rounding issues by trimming the excess
    return resized[: new_size[0], : new_size[1]]


def init_service() -> None:
    from picamera2 import Picamera2  # pyright: ignore [reportMissingImports]
    from pyzbar.pyzbar import decode

    picam2 = Picamera2()
    preview_config = picam2.create_still_configuration(
        {
            'format': 'RGB888',
            'size': (HeadlessWidget.width * 2, HeadlessWidget.height * 2),
        },
    )
    picam2.configure(preview_config)
    picam2.set_controls({'AwbEnable': True})

    picam2.start()

    def start_camera_viewfinder(start_event: CameraStartViewfinderEvent) -> None:
        regex_pattern = start_event.barcode_pattern
        regex = re.compile(regex_pattern) if regex_pattern is not None else None
        last_match = 0

        display = HeadlessWidget._display  # noqa: SLF001

        def check_image(barcodes: list) -> None:
            nonlocal last_match
            if time.time() - last_match < THROTTL_TIME:
                return
            if regex is None:
                return
            last_match = time.time()

            for barcode in barcodes:
                code = barcode.data.decode()
                logger.info(
                    'Read barcode, decoded value',
                    extra={'decoded_value': code},
                )
                match = regex.match(code)
                if match:
                    logger.info(
                        'Pattern match',
                        extra={
                            'pattern': regex_pattern,
                            'match': match.groupdict(),
                            'decoded_value': code,
                        },
                    )
                    dispatch(
                        CameraBarcodeAction(code=code, match=match.groupdict()),
                    )

        def feed_viewfinder(_: object) -> None:
            data = picam2.capture_array('main')

            barcodes = decode(data)
            if len(barcodes) > 0:
                check_image(barcodes)

            data = resize_image(data)
            data = np.rot90(data, 2)

            # Mirror the image
            data = data[:, ::-1, :3].astype(np.uint16)
            color = (
                ((data[:, :, 0] & 0xF8) << 8)
                | ((data[:, :, 1] & 0xFC) << 3)
                | (data[:, :, 2] >> 3)
            )
            data_bytes = bytes(
                np.dstack(((color >> 8) & 0xFF, color & 0xFF)).flatten().tolist(),
            )

            display._block(  # noqa: SLF001
                0,
                0,
                HeadlessWidget.width - 1,
                HeadlessWidget.height - 1,
                data_bytes,
            )

        feed_viewfinder_scheduler = Clock.schedule_interval(feed_viewfinder, 0.03)
        HeadlessWidget.pause()

        def handle_stop_viewfinder(_: CameraStopViewfinderEvent) -> None:
            feed_viewfinder_scheduler.cancel()
            HeadlessWidget.resume()
            cancel_subscription()

        cancel_subscription = subscribe_event(
            CameraStopViewfinderEvent,
            handle_stop_viewfinder,
        )

    subscribe_event(CameraStartViewfinderEvent, start_camera_viewfinder)

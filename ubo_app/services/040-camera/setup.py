# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import headless_kivy_pi.config
import numpy as np
from debouncer import DebounceOptions, debounce
from kivy.clock import Clock
from pyzbar.pyzbar import decode

from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.services.camera import (
    CameraReportBarcodeAction,
    CameraStartViewfinderEvent,
    CameraStopViewfinderEvent,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from numpy._typing import NDArray

THROTTL_TIME = 0.5


def resize_image(
    image: NDArray[np.uint8],
    new_size: tuple[int, int] = (
        headless_kivy_pi.config.width(),
        headless_kivy_pi.config.height(),
    ),
) -> NDArray[np.uint8]:
    scale_x = image.shape[1] / new_size[1]
    scale_y = image.shape[0] / new_size[0]

    # Use slicing to downsample the image
    resized = image[:: int(scale_y), :: int(scale_x)]

    # Handle any rounding issues by trimming the excess
    return resized[: new_size[0], : new_size[1]]


@debounce(
    wait=THROTTL_TIME,
    options=DebounceOptions(leading=True, trailing=False, time_window=THROTTL_TIME),
)
async def check_codes(codes: list[str]) -> None:
    dispatch(CameraReportBarcodeAction(codes=codes))


def run_fake_camera() -> None:  # pragma: no cover
    async def provide() -> None:
        while True:
            await asyncio.sleep(0.1)
            path = Path('/tmp/qrcode_input.txt')  # noqa: S108
            if not path.exists():
                continue
            data = path.read_text().strip()
            path.unlink(missing_ok=True)
            await check_codes([data])

    def run_provider() -> None:
        def set_task(task: asyncio.Task) -> None:
            def stop() -> None:
                task.cancel()
                cancel_subscription()

            cancel_subscription = subscribe_event(
                CameraStopViewfinderEvent,
                stop,
            )

        create_task(provide(), set_task)

    subscribe_event(
        CameraStartViewfinderEvent,
        run_provider,
    )


def init_service() -> None:
    if not IS_RPI:
        run_fake_camera()
        return

    from picamera2 import Picamera2  # pyright: ignore [reportMissingImports]

    picam2 = Picamera2()
    preview_config = picam2.create_still_configuration(
        {
            'format': 'RGB888',
            'size': (
                headless_kivy_pi.config.width() * 2,
                headless_kivy_pi.config.height() * 2,
            ),
        },
    )
    picam2.configure(preview_config)
    picam2.set_controls({'AwbEnable': True})

    picam2.start()

    def start_camera_viewfinder() -> None:
        display = headless_kivy_pi.config._display  # noqa: SLF001
        if not display:
            return

        def feed_viewfinder(_: object) -> None:
            display = headless_kivy_pi.config._display  # noqa: SLF001
            if not display:
                return
            data = picam2.capture_array('main')

            barcodes = decode(data)
            if len(barcodes) > 0:
                create_task(
                    check_codes(
                        codes=[barcode.data.decode() for barcode in barcodes],
                    ),
                )

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
                headless_kivy_pi.config.width() - 1,
                headless_kivy_pi.config.height() - 1,
                data_bytes,
            )

        feed_viewfinder_scheduler = Clock.schedule_interval(feed_viewfinder, 0.03)

        headless_kivy_pi.config.pause()

        def handle_stop_viewfinder() -> None:
            feed_viewfinder_scheduler.cancel()
            headless_kivy_pi.config.resume()
            cancel_subscription()

        cancel_subscription = subscribe_event(
            CameraStopViewfinderEvent,
            handle_stop_viewfinder,
        )

    subscribe_event(CameraStartViewfinderEvent, start_camera_viewfinder)

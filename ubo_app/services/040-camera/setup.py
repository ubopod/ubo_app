# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

import headless_kivy_pi.config
import numpy as np
import png
from debouncer import DebounceOptions, debounce
from kivy.clock import Clock, mainthread
from picamera2 import Picamera2  # pyright: ignore [reportMissingImports]
from pyzbar.pyzbar import decode
from ubo_gui.page import PageWidget

from ubo_app.store.core import CloseApplicationEvent, OpenApplicationEvent
from ubo_app.store.main import dispatch, subscribe_event
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
    *,
    new_size: tuple[int, int],
) -> NDArray[np.uint8]:
    scale_x = max(image.shape[1] / new_size[1], 1)
    scale_y = max(image.shape[0] / new_size[0], 1)

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


class CameraApplication(PageWidget):
    def go_back(self: CameraApplication) -> bool:
        return True


def initialize_camera() -> Picamera2:
    picamera2 = Picamera2()
    preview_config = picamera2.create_still_configuration(
        {
            'format': 'RGB888',
            'size': (
                headless_kivy_pi.config.width() * 2,
                headless_kivy_pi.config.height() * 2,
            ),
        },
    )
    picamera2.configure(preview_config)
    picamera2.set_controls({'AwbEnable': True})

    picamera2.start()

    return picamera2


def feed_viewfinder(picamera2: Picamera2) -> None:
    width = headless_kivy_pi.config.width()
    height = headless_kivy_pi.config.height()
    display = headless_kivy_pi.config._display  # noqa: SLF001

    if not IS_RPI:
        path = Path('/tmp/qrcode_input.txt')  # noqa: S108
        if path.exists():
            barcodes = [path.read_text().strip()]
            path.unlink(missing_ok=True)
            create_task(check_codes(codes=barcodes))
            return

    qrcode_path = Path('/tmp/qrcode_input.png')  # noqa: S108
    if qrcode_path.exists():
        with qrcode_path.open('rb') as file:
            reader = png.Reader(file)
            width, height, data, _ = reader.read()
            data = np.array(list(data)).reshape((height, width, 4))
        qrcode_path.unlink(missing_ok=True)
    else:
        data = picamera2.capture_array('main')

    barcodes = decode(data)
    if len(barcodes) > 0:
        create_task(
            check_codes(
                codes=[barcode.data.decode() for barcode in barcodes],
            ),
        )

    if not display:
        return

    data = resize_image(data, new_size=(width, height))
    data = np.rot90(data, 2)

    # Mirror the image
    data = data[:, ::-1, :3].astype(np.uint16)

    # Render an empty rounded rectangle
    margin = 15
    thickness = 7

    lines = [
        ((margin, width - margin), (margin, margin + thickness)),
        (
            (margin, width - margin),
            (height - margin - thickness, height - margin),
        ),
        (
            (margin, margin + thickness),
            (margin + thickness, height - margin - thickness),
        ),
        (
            (width - margin - thickness, width - margin),
            (margin + thickness, height - margin - thickness),
        ),
    ]
    for line in lines:
        data[line[0][0] : line[0][1], line[1][0] : line[1][1]] = (
            0xFF - data[line[0][0] : line[0][1], line[1][0] : line[1][1]]
        ) // 2

    color = (
        (data[:, :, 2] & 0xF8) << 8 | (data[:, :, 1] & 0xFC) << 3 | data[:, :, 0] >> 3
    )

    data_bytes = bytes(
        np.dstack(((color >> 8) & 0xFF, color & 0xFF)).flatten().tolist(),
    )

    display._block(0, 0, width - 1, height - 1, data_bytes)  # noqa: SLF001


@mainthread
def start_camera_viewfinder() -> None:
    picamera2 = initialize_camera()
    is_running = True

    fs_lock = Lock()
    application = CameraApplication()
    dispatch(OpenApplicationEvent(application=application))

    def feed_viewfinder_locked(_: object) -> None:
        with fs_lock:
            if not is_running:
                return
            feed_viewfinder(picamera2)

    feed_viewfinder_scheduler = Clock.schedule_interval(feed_viewfinder_locked, 0.04)

    headless_kivy_pi.config.pause()

    def handle_stop_viewfinder() -> None:
        with fs_lock:
            nonlocal is_running
            is_running = False
            feed_viewfinder_scheduler.cancel()
            dispatch(CloseApplicationEvent(application=application))
            headless_kivy_pi.config.resume()
            cancel_subscription()
            picamera2.stop()

    cancel_subscription = subscribe_event(
        CameraStopViewfinderEvent,
        handle_stop_viewfinder,
    )


def init_service() -> None:
    subscribe_event(
        CameraStartViewfinderEvent,
        start_camera_viewfinder,
    )

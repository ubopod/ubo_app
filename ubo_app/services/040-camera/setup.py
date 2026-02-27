# pyright: reportMissingModuleSource=false
# ruff: noqa: D100, D103
from __future__ import annotations

import asyncio
import math
import threading
import time
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

import numpy as np
import png
from debouncer import DebounceOptions, debounce

from ubo_app.constants import HEIGHT, WIDTH
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    CloseApplicationAction,
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.camera import (
    CameraDetectAction,
    CameraDetectEvent,
    CameraInstallDriverEvent,
    CameraReportBarcodeAction,
    CameraReportImageEvent,
    CameraRestoreDefaultEvent,
    CameraSetAvailableCamerasAction,
    CameraSetIndexAction,
    CameraStartViewfinderEvent,
    CameraState,
    CameraStopViewfinderEvent,
)
from ubo_app.store.services.display import DisplayPauseAction, DisplayResumeAction
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.persistent_store import register_persistent_store
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy._typing._array_like import NDArray

    from ubo_app.utils.types import Subscriptions

    from .camera_backend import CameraBackend

THROTTL_TIME = 0.5
VIEWFINDER_INTERVAL = 0.04


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
def check_codes(codes: list[str]) -> None:
    store.dispatch(CameraReportBarcodeAction(codes=codes))


class _RepeatingTimer:
    """A simple repeating timer using threading."""

    def __init__(self, interval: float, callback: Callable[[object], None]) -> None:
        self._interval = interval
        self._callback = callback
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stopped.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stopped.wait(self._interval):
            self._callback(None)

    def cancel(self) -> None:
        self._stopped.set()


def start_camera_viewfinder_session() -> None:
    """Start a camera viewfinder session (replaces CameraApplication widget)."""
    import uuid

    instance_id = uuid.uuid4().hex
    camera = None
    is_running = True
    fs_lock = Lock()

    @store.autorun(lambda state: state.camera.selected_camera_index)
    def _handle_camera_change(index: int) -> None:
        nonlocal camera
        if not is_running:
            return
        if camera:
            camera.stop()
            camera.close()
        camera = initialize_camera(index)

    def feed_viewfinder_locked(_: object) -> None:
        with fs_lock:
            if not is_running:
                return
            feed_viewfinder(camera)

    timer = _RepeatingTimer(VIEWFINDER_INTERVAL, feed_viewfinder_locked)
    timer.start()

    store.dispatch(DisplayPauseAction())

    def handle_stop_viewfinder(_: object = None) -> None:
        unsubscribe()
        with fs_lock:
            nonlocal is_running
            is_running = False
            timer.cancel()
            store.dispatch(
                CloseApplicationAction(application_instance_id=instance_id),
                DisplayResumeAction(),
            )
            if camera:
                camera.stop()
                camera.close()

    unsubscribe = store.subscribe_event(
        CameraStopViewfinderEvent,
        handle_stop_viewfinder,
    )


def initialize_camera(camera_index: int = 0) -> CameraBackend | None:
    """Initialize the appropriate camera backend based on platform.

    Args:
        camera_index: Camera device index (default: 0, only used on non-RPI platforms)

    Returns:
        Camera backend instance or None if initialization fails

    """
    try:
        width = WIDTH * 2
        height = HEIGHT * 2

        if IS_RPI:
            from picamera2_backend import PiCamera2Backend

            logger.info(
                'Initializing camera with index {index}',
                extra={'index': camera_index},
            )
            camera = PiCamera2Backend(
                width=width,
                height=height,
                camera_index=camera_index,
            )
        else:
            from opencv_backend import OpenCVCameraBackend

            logger.info(
                'Initializing camera with index {index}',
                extra={'index': camera_index},
            )
            camera = OpenCVCameraBackend(
                width=width,
                height=height,
                camera_index=camera_index,
            )

        camera.start()
    except Exception:
        report_service_error()
        logger.exception('Failed to initialize camera.')
        return None
    else:
        return camera


def feed_viewfinder(camera: CameraBackend | None) -> None:
    width = WIDTH
    height = HEIGHT

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
    elif camera:
        data = camera.capture_array('main')
    else:
        data = None

    if data is not None:
        from pyzbar.pyzbar import decode

        barcodes = decode(data)
        create_task(
            check_codes(codes=[barcode.data.decode() for barcode in barcodes]),
        )

        data = resize_image(data, new_size=(width, height))

        # Mirror the image
        data = np.rot90(data, 2)[:, ::-1, :3]

        viewfinder_data = data.astype(np.uint16)

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
            viewfinder_data[line[0][0] : line[0][1], line[1][0] : line[1][1]] = (
                0xFF - viewfinder_data[line[0][0] : line[0][1], line[1][0] : line[1][1]]
            ) // 2

        color = (
            (viewfinder_data[:, :, 2] & 0xF8) << 8
            | (viewfinder_data[:, :, 1] & 0xFC) << 3
            | viewfinder_data[:, :, 0] >> 3
        )

        data_bytes = bytes(
            np.dstack(((color >> 8) & 0xFF, color & 0xFF)).flatten().tolist(),
        )

        from ubo_app.display import display

        display.render_block(
            rectangle=(0, 0, width - 1, height - 1),
            data_bytes=data_bytes,
            bypass_pause=True,
        )

        store._dispatch(  # noqa: SLF001
            [
                CameraReportImageEvent(
                    timestamp=time.time(),
                    data=data.tobytes(),
                    width=width,
                    height=height,
                ),
            ],
        )


async def _install_camera_driver(event: CameraInstallDriverEvent) -> None:
    from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
    from ubo_app.store.core.types import RebootAction
    from ubo_app.store.services.notifications import (
        Chime,
        Notification,
        NotificationDispatchItem,
        NotificationDisplayType,
        NotificationsAddAction,
    )

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='camera_install_driver',
                title='Camera Driver',
                content=f'Installing {event.make} {event.model} driver...',
                display_type=NotificationDisplayType.STICKY,
                color=WARNING_COLOR,
                icon='󰄁',
                show_dismiss_action=False,
                progress=math.nan,
            ),
        ),
    )
    result = await send_command(
        'camera',
        'install_driver',
        event.make,
        event.model,
        event.variant,
        has_output=True,
    )
    if result == 'installed':
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='camera_install_driver',
                    title='Camera Driver',
                    content=f'{event.make} {event.model} installed successfully.\n'
                    'Reboot required for changes to take effect.',
                    display_type=NotificationDisplayType.STICKY,
                    color=SUCCESS_COLOR,
                    icon='󰄬',
                    chime=Chime.DONE,
                    show_dismiss_action=True,
                    actions=[
                        NotificationDispatchItem(
                            icon='󰜉',
                            store_action=RebootAction(),
                        ),
                    ],
                ),
            ),
        )
    else:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='camera_install_driver',
                    title='Camera Driver',
                    content=f'Failed to install {event.make} {event.model} driver',
                    display_type=NotificationDisplayType.FLASH,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )


async def _restore_default_camera(_: CameraRestoreDefaultEvent) -> None:
    from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR, WARNING_COLOR
    from ubo_app.store.core.types import RebootAction
    from ubo_app.store.services.notifications import (
        Chime,
        Notification,
        NotificationDispatchItem,
        NotificationDisplayType,
        NotificationsAddAction,
    )

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='camera_restore_default',
                title='Camera',
                content='Restoring default camera configuration...',
                display_type=NotificationDisplayType.STICKY,
                color=WARNING_COLOR,
                icon='󰁯',
                show_dismiss_action=False,
                progress=math.nan,
            ),
        ),
    )
    # Allow the UI to fully render the progress notification before proceeding.
    # Without this delay, the operation completes so fast that the replacement
    # notification is dispatched before the STICKY view finishes rendering,
    # causing the progress notification to stay visible instead of updating.
    await asyncio.sleep(0.5)
    result = await send_command(
        'camera',
        'restore_default',
        has_output=True,
    )
    if result == 'restored':
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='camera_restore_default',
                    title='Camera',
                    content='Default camera restored successfully.\n'
                    'Reboot required for changes to take effect.',
                    display_type=NotificationDisplayType.STICKY,
                    color=SUCCESS_COLOR,
                    icon='󰄬',
                    chime=Chime.DONE,
                    show_dismiss_action=True,
                    actions=[
                        NotificationDispatchItem(
                            icon='󰜉',
                            store_action=RebootAction(),
                        ),
                    ],
                ),
            ),
        )
    else:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='camera_restore_default',
                    title='Camera',
                    content='Failed to restore default camera configuration',
                    display_type=NotificationDisplayType.FLASH,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                ),
            ),
        )


def start_camera_viewfinder() -> None:
    start_camera_viewfinder_session()


async def detect_and_update_cameras() -> None:
    """Detect available cameras and update state."""
    try:
        if IS_RPI:
            from utils import detect_available_cameras_picamera2

            logger.info('Starting Picamera2 camera detection...')
            available = detect_available_cameras_picamera2()
        else:
            from utils import detect_available_cameras

            logger.info('Starting OpenCV camera detection...')
            available = detect_available_cameras()

        logger.info(
            'Camera detection complete: {count} camera(s) found',
            extra={'count': len(available), 'indices': available},
        )
        store.dispatch(CameraSetAvailableCamerasAction(available_cameras=available))
    except Exception:
        logger.exception('Error during camera detection')
        store.dispatch(CameraSetAvailableCamerasAction(available_cameras=[]))


def handle_camera_detect(_: CameraDetectEvent) -> None:
    """Handle camera detection event."""
    logger.info('Camera detect event received, starting detection...')
    create_task(detect_and_update_cameras())


CAMERA_MENU_ID = 'camera:main'


def _register_camera_action_handlers() -> None:
    """Register action handlers for camera menu items."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
    )

    if 'camera:detect' in get_registered_actions():
        return

    register_action(
        'camera:detect',
        lambda: store.dispatch(CameraDetectAction()),
    )


def _register_camera_index_actions(available_cameras: tuple[int, ...]) -> None:
    """Register action handlers for each camera index."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
        unregister_action,
    )

    for action_id in list(get_registered_actions()):
        if action_id.startswith('camera:select:'):
            unregister_action(action_id)

    for index in available_cameras:
        def _make_handler(i: int) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(CameraSetIndexAction(index=i))

            return _handler

        register_action(f'camera:select:{index}', _make_handler(index))


@store.autorun(lambda state: state.camera)
def update_camera_dynamic_menu(state: CameraState) -> None:
    """Update the dynamic menu for camera settings."""
    _register_camera_action_handlers()
    _register_camera_index_actions(state.available_cameras)

    items: list[MenuItemData] = []

    for index in state.available_cameras:
        is_selected = index == state.selected_camera_index
        items.append(
            MenuItemData(
                key=f'camera:index:{index}',
                label=f'Camera {index}',
                icon='\uf030',
                action_id=f'camera:select:{index}',
                background_color='#00ff00' if is_selected else None,
            ),
        )

    items.append(
        MenuItemData(
            key='camera:detect',
            label='Detect Cameras',
            icon='󰄄',
            action_id='camera:detect',
        ),
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=CAMERA_MENU_ID,
            title='Camera Settings',
            heading='Select Camera Device',
            sub_heading=f'Current: Camera {state.selected_camera_index}'
            if state.available_cameras
            else 'No cameras detected',
            items=tuple(items),
            placeholder='No cameras detected. Click "Detect Cameras" to scan.'
            if not state.available_cameras
            else '',
        ),
    )


def init_service() -> Subscriptions:
    # Register camera settings menu
    store.dispatch(
        RegisterSettingAppAction(
            priority=1,
            category=SettingsCategory.HARDWARE,
            label='Camera',
            icon='',
        ),
    )

    from ubo_app.store.core.view_registry import (
        create_settings_path_matcher,
        register_path_menu_matcher,
    )

    register_path_menu_matcher(
        'camera:settings',
        create_settings_path_matcher('camera:', CAMERA_MENU_ID),
    )

    # Detect cameras on startup
    create_task(detect_and_update_cameras())

    # Register persistent storage for selected camera index
    register_persistent_store(
        'camera_selected_index',
        lambda state: state.camera.selected_camera_index,
    )

    # Register persistent storage for camera type
    register_persistent_store(
        'camera_type',
        lambda state: state.camera.camera_type,
    )

    return [
        store.subscribe_event(
            CameraStartViewfinderEvent,
            start_camera_viewfinder,
        ),
        store.subscribe_event(
            CameraDetectEvent,
            handle_camera_detect,
        ),
        store.subscribe_event(
            CameraInstallDriverEvent,
            _install_camera_driver,
        ),
        store.subscribe_event(
            CameraRestoreDefaultEvent,
            _restore_default_camera,
        ),
    ]

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
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushApplicationAction,
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
    CameraStartViewfinderAction,
    CameraStartViewfinderEvent,
    CameraState,
)
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


class _ViewfinderSession:
    """Manages a camera viewfinder session lifecycle."""

    def __init__(self) -> None:
        self.camera: CameraBackend | None = None
        self.is_running = True
        self.fs_lock = Lock()
        self._event_unsubscribe: Callable[[], None] = lambda: None
        self._stack_unsubscribe: Callable[[], None] = lambda: None

    def handle_camera_change(self, index: int) -> None:
        """Reinitialize camera when selected index changes."""
        if not self.is_running:
            return
        if self.camera:
            self.camera.stop()
            self.camera.close()
        self.camera = initialize_camera(index)

    def feed_locked(self, _: object) -> None:
        """Feed viewfinder under lock."""
        with self.fs_lock:
            if not self.is_running:
                return
            feed_viewfinder(self.camera)

    def cleanup(self, timer: _RepeatingTimer) -> None:
        """Shut down the viewfinder session and release the camera."""
        self._event_unsubscribe()
        self._stack_unsubscribe()
        with self.fs_lock:
            if not self.is_running:
                return
            self.is_running = False
            timer.cancel()
            if self.camera:
                self.camera.stop()
                self.camera.close()


def _is_viewfinder_on_stack(
    stack: tuple[object, ...],
) -> bool:
    from ubo_app.store.core.types.stack_items import ApplicationStackItem

    return any(
        isinstance(item, ApplicationStackItem)
        and item.application_id == 'camera:viewfinder'
        for item in stack
    )

def start_camera_viewfinder_session() -> None:
    """Start a camera viewfinder session (replaces CameraApplication widget)."""
    from ubo_app.store.core.types import StackChangedEvent

    session = _ViewfinderSession()

    @store.autorun(lambda state: state.camera.selected_camera_index)
    def _handle_camera_change(index: int) -> None:
        session.handle_camera_change(index)

    timer = _RepeatingTimer(VIEWFINDER_INTERVAL, session.feed_locked)
    timer.start()

    store.dispatch(StackPushApplicationAction(application_id='camera:viewfinder'))

    def _handle_stack_changed(event: StackChangedEvent) -> None:
        if session.is_running and not _is_viewfinder_on_stack(event.stack):
            session.cleanup(timer)

    session._stack_unsubscribe = store.subscribe_event(  # noqa: SLF001
        StackChangedEvent,
        _handle_stack_changed,
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
        logger.info('[camera] found mock PNG %s', qrcode_path)
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
        decoded_codes = [barcode.data.decode() for barcode in barcodes]
        logger.info(
            '[camera] pyzbar decoded %d barcode(s): %r (data shape=%s)',
            len(decoded_codes),
            decoded_codes,
            getattr(data, 'shape', 'N/A'),
        )
        create_task(
            check_codes(codes=decoded_codes),
        )

        data = resize_image(data, new_size=(width, height))

        # Mirror the image
        data = np.rot90(data, 2)[:, ::-1, :3]

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
    register_action(
        'camera:open-viewfinder',
        lambda: store.dispatch(
            CameraStartViewfinderAction(pattern=None),
        ),
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

    items.append(
        MenuItemData(
            key='camera:viewfinder',
            label='View Finder',
            icon='󰄀',
            action_id='camera:open-viewfinder',
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

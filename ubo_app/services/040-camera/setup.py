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
    FrameStreamDataEvent,
    MenuItemData,
    OpenRenderAction,
    RegisterSettingAppAction,
    SettingsCategory,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.camera import (
    CameraDetectAction,
    CameraDetectAdvertiseEvent,
    CameraDetectEvent,
    CameraInstallDriverEvent,
    CameraReportBarcodeAction,
    CameraReportImageEvent,
    CameraRestoreDefaultEvent,
    CameraSetAvailableCamerasAction,
    CameraSetSelectedSourceAction,
    CameraSource,
    CameraSourceKind,
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
# How long to wait for remote clients to (re-)register after a detect cycle
# starts before we finalise the camera list.
REMOTE_REGISTRATION_WINDOW = 1.5


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


def _parse_local_index(source_id: str) -> int | None:
    """Return the integer index from a `local:N` source id, or None for remote."""
    prefix = 'local:'
    if not source_id.startswith(prefix):
        return None
    try:
        return int(source_id.removeprefix(prefix))
    except ValueError:
        return None


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
        self.current_source_id: str = ''
        self._event_unsubscribe: Callable[[], None] = lambda: None
        self._stack_unsubscribe: Callable[[], None] = lambda: None

    def handle_source_change(self, source_id: str) -> None:
        """Switch the local backend to match the selected source.

        Remote sources push frames over gRPC — there's no local backend to
        spin up, so we just tear down whatever we had.
        """
        if not self.is_running:
            return
        self.current_source_id = source_id
        if self.camera:
            self.camera.stop()
            self.camera.close()
            self.camera = None
        local_index = _parse_local_index(source_id)
        if local_index is not None:
            self.camera = initialize_camera(local_index)

    def feed_locked(self, _: object) -> None:
        """Feed viewfinder under lock."""
        with self.fs_lock:
            if not self.is_running:
                return
            feed_viewfinder(self.camera, self.current_source_id)

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
    from ubo_app.store.core.types.stack_items import RenderStackItem

    return any(
        isinstance(item, RenderStackItem)
        and item.stream_id == 'camera:viewfinder'
        for item in stack
    )

def start_camera_viewfinder_session() -> None:
    """Start a camera viewfinder session (replaces CameraApplication widget)."""
    from ubo_app.store.core.types import StackChangedEvent

    session = _ViewfinderSession()

    @store.autorun(lambda state: state.camera.selected_source_id)
    def _handle_source_change(source_id: str) -> None:
        session.handle_source_change(source_id)

    timer = _RepeatingTimer(VIEWFINDER_INTERVAL, session.feed_locked)
    timer.start()

    store.dispatch(
        OpenRenderAction(
            kind='frame_stream',
            stream_id='camera:viewfinder',
        ),
    )

    def _handle_stack_changed(event: StackChangedEvent) -> None:
        if not (session.is_running and not _is_viewfinder_on_stack(event.stack)):
            return
        session.cleanup(timer)

        # If the user backed out of the viewfinder without scanning or
        # cancelling, the camera reducer's queue still holds the pending
        # input description and a follow-up `InputDemandAction` would be
        # silently appended without re-prompting. Cancelling here drains
        # the queue (via the reducer's `InputResolveAction` match) and
        # clears the matching `camera:qrcode:*` notification. A successful
        # scan dispatches `InputProvideAction` *before* the viewfinder
        # leaves the stack, so the post-cleanup queue is already empty
        # and this read no-ops.
        from ubo_app.store.input.types import InputCancelAction, QRCodeInputDescription

        @store.with_state(lambda state: state.camera.queue)
        def _cancel_if_pending(queue: list[QRCodeInputDescription]) -> None:
            if queue:
                store.dispatch(InputCancelAction(id=queue[0].id))

        _cancel_if_pending()

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


def feed_viewfinder(camera: CameraBackend | None, source_id: str) -> None:
    """Pull a frame from the local backend and emit a CameraReportImageEvent.

    Frame post-processing (QR decode + display mirror) lives in
    `_handle_report_image` so remote-pushed frames go through the same path.
    Tagging the event with `source_id` lets the handler accept only frames
    from the selected source.
    """
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
                    source_id=source_id,
                ),
            ],
        )


@store.with_state(lambda state: state.camera.selected_source_id)
def _selected_source_id(source_id: str) -> str:
    return source_id


@store.with_state(lambda state: state.camera.pending_remote_registrations)
def _snapshot_pending_remote_registrations(
    pending: tuple[CameraSource, ...],
) -> tuple[CameraSource, ...]:
    return pending


def _handle_report_image(event: CameraReportImageEvent) -> None:
    """Decode QR codes + forward to the display mirror.

    Runs for every CameraReportImageEvent regardless of origin (local timer
    or remote gRPC dispatch). Frames whose `source_id` doesn't match the
    currently selected source are dropped — only the active camera should
    drive QR scanning and display.
    """
    selected = _selected_source_id()
    if event.source_id and event.source_id != selected:
        return
    if event.width <= 0 or event.height <= 0 or not event.data:
        return

    expected_size = event.width * event.height * 3
    if len(event.data) != expected_size:
        logger.warning(
            '[camera] dropping frame with unexpected payload size '
            '(got %d bytes, expected %d for %dx%d RGB)',
            len(event.data),
            expected_size,
            event.width,
            event.height,
        )
        return

    try:
        from pyzbar.pyzbar import decode

        frame = np.frombuffer(event.data, dtype=np.uint8).reshape(
            event.height,
            event.width,
            3,
        )
        barcodes = decode(frame)
        decoded_codes = [barcode.data.decode() for barcode in barcodes]
        if decoded_codes:
            logger.debug(
                '[camera] pyzbar decoded %d barcode(s): %r',
                len(decoded_codes),
                decoded_codes,
            )
            create_task(check_codes(codes=decoded_codes))
    except Exception:
        logger.exception('[camera] pyzbar decode failed')

    store._dispatch(  # noqa: SLF001
        [
            FrameStreamDataEvent(
                stream_id='camera:viewfinder',
                data=event.data,
                width=event.width,
                height=event.height,
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
                            label='Reboot',
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
                            label='Reboot',
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


def _close_camera_viewfinder_on_input_resolved(_: object) -> None:
    """Close the camera viewfinder once an input demand resolves.

    Fires on ``InputProvideEvent`` (successful scan) — the
    ``pop_queue`` path inside the camera reducer no longer pops the
    stack itself (doing so blindly over-popped when the cancel arrived
    from ``on_close_id`` instead of a scan), so the viewfinder needs
    an explicit close here. Identifies the viewfinder by its
    ``stream_id`` so we can't accidentally pop the wrong stack item.
    No-op when the viewfinder isn't on the stack (the input may have
    been provided by a different service — file-system, web-ui, etc.).
    """
    from ubo_app.store.core.types import StackPopItemAction
    from ubo_app.store.core.types.stack_items import (
        RenderStackItem,
        StackItemType,
    )

    @store.with_state(lambda state: state.main.stack)
    def _pop_viewfinder(stack: tuple[StackItemType, ...]) -> None:
        viewfinder = next(
            (
                item
                for item in stack
                if isinstance(item, RenderStackItem)
                and item.stream_id == 'camera:viewfinder'
            ),
            None,
        )
        if viewfinder is not None:
            store.dispatch(StackPopItemAction(item_id=viewfinder.id))

    _pop_viewfinder()


def _local_label(index: int) -> str:
    return f'Local Camera {index}'


async def detect_and_update_cameras() -> None:
    """Run a detection cycle.

    Probe local hardware, wait for remote clients to (re-)register, then
    publish the merged source list.
    """
    try:
        if IS_RPI:
            from utils import detect_available_cameras_picamera2

            logger.info('Starting Picamera2 camera detection...')
            available_local_indices = detect_available_cameras_picamera2()
        else:
            from utils import detect_available_cameras

            logger.info('Starting OpenCV camera detection...')
            available_local_indices = detect_available_cameras()

        logger.info(
            'Local camera detection found %d device(s); waiting %ss for '
            'remote registrations...',
            len(available_local_indices),
            REMOTE_REGISTRATION_WINDOW,
        )

        await asyncio.sleep(REMOTE_REGISTRATION_WINDOW)

        local_sources = tuple(
            CameraSource(
                id=f'local:{index}',
                label=_local_label(index),
                kind=CameraSourceKind.LOCAL,
            )
            for index in available_local_indices
        )
        # Snapshot pending registrations after the window closes; the reducer
        # clears the staging area on CameraSetAvailableCamerasAction.
        remote_sources = _snapshot_pending_remote_registrations()
        merged = [*local_sources, *remote_sources]

        logger.info(
            'Camera detection complete: %d local + %d remote source(s)',
            len(local_sources),
            len(remote_sources),
        )
        store.dispatch(
            CameraSetAvailableCamerasAction(available_cameras=merged),
        )
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


def _register_source_actions(available: tuple[CameraSource, ...]) -> None:
    """Register one menu-action per available source so the user can pick it."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
        unregister_action,
    )

    for action_id in list(get_registered_actions()):
        if action_id.startswith('camera:select:'):
            unregister_action(action_id)

    for source in available:
        def _make_handler(source_id: str) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(CameraSetSelectedSourceAction(source_id=source_id))

            return _handler

        register_action(f'camera:select:{source.id}', _make_handler(source.id))


def _short_label_for(source: CameraSource) -> str:
    """Trim the label so it fits in the dynamic menu's narrow rows."""
    return source.label


@store.autorun(lambda state: state.camera)
def update_camera_dynamic_menu(state: CameraState) -> None:
    """Update the dynamic menu for camera settings."""
    _register_camera_action_handlers()
    _register_source_actions(state.available_cameras)

    items: list[MenuItemData] = []
    selected_label = ''

    for source in state.available_cameras:
        is_selected = source.id == state.selected_source_id
        if is_selected:
            selected_label = source.label
        icon = '' if source.kind is CameraSourceKind.LOCAL else '󰀂'
        items.append(
            MenuItemData(
                key=f'camera:source:{source.id}',
                label=_short_label_for(source),
                icon=icon,
                action_id=f'camera:select:{source.id}',
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

    sub_heading = f'Current: {selected_label}' if selected_label else (
        'No cameras detected' if not state.available_cameras else 'No source selected'
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=CAMERA_MENU_ID,
            title='Camera Settings',
            heading='Select Camera Source',
            sub_heading=sub_heading,
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

    # Register persistent storage for selected source id (replaces the
    # legacy `camera_selected_index` int key; the reducer migrates old
    # values on first init).
    register_persistent_store(
        'camera_selected_source_id',
        lambda state: state.camera.selected_source_id,
    )

    # Register persistent storage for camera type
    register_persistent_store(
        'camera_type',
        lambda state: state.camera.camera_type,
    )

    from ubo_app.store.input.types import InputProvideEvent

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
            CameraDetectAdvertiseEvent,
            lambda _event: None,
        ),
        store.subscribe_event(
            CameraReportImageEvent,
            _handle_report_image,
        ),
        store.subscribe_event(
            CameraInstallDriverEvent,
            _install_camera_driver,
        ),
        store.subscribe_event(
            CameraRestoreDefaultEvent,
            _restore_default_camera,
        ),
        store.subscribe_event(
            InputProvideEvent,
            _close_camera_viewfinder_on_input_resolved,
        ),
    ]

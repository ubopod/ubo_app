"""Implementation of a file system navigation application."""

from __future__ import annotations

import functools
import mimetypes
import stat
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuItemData,
    StackPushApplicationAction,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.input.types import PathInputDescription
from ubo_app.store.main import store
from ubo_app.store.services.audio import (
    AudioPlayAudioSampleAction,
    AudioSample,
    AudioStopPlaybackAction,
)
from ubo_app.store.services.file_system import (
    FileSystemCopyAction,
    FileSystemEvent,
    FileSystemMoveAction,
    FileSystemRemoveAction,
    FileSystemReportSelectionAction,
    FileSystemSelectorPushedAction,
    PathSelectorConfig,
)
from ubo_app.store.services.notification_helpers import create_notification_action
from ubo_app.store.services.notifications import (
    Notification,
    NotificationApplicationItem,
    NotificationDispatchItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.color import escape_markup
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.file_system import human_readable_size
from ubo_app.utils.input import ubo_input

if TYPE_CHECKING:
    from collections.abc import Callable

    _SelectFn = Callable[[Path], None]

FILE_VIEWER_SIZE_LIMIT = 2**11  # 2 KiB

# Module-level tracking for file browser action IDs
_file_browser_action_ids: dict[str, list[str]] = {}

# Track event unsubscribers for each menu_id. When a new _items_generator
# is created for a path that already has one, the old is cleaned up first.
_menu_unsubscribers: dict[str, Callable[[], None]] = {}

# Track which menu_ids were created in selector mode (for cleanup on select).
_selector_menu_ids: list[str] = []

# Track currently playing audio file path (None = not playing).
_audio_playing: list[Path | None] = [None]


def _file_info(path: Path) -> str:
    return f"""[b]Type:[/b] {
        'Directory'
        if path.is_dir()
        else 'Symlink'
        if path.is_symlink()
        else 'Block Device'
        if path.is_block_device()
        else 'Character Device'
        if path.is_char_device()
        else 'FIFO'
        if path.is_fifo()
        else 'Socket'
        if path.is_socket()
        else 'File'
    }
[b]Path:[/b] {escape_markup(path.as_posix())}
[b]Size:[/b] {'-' if path.is_dir() else human_readable_size(path.stat().st_size)}
[b]Owner:[/b] {path.owner()}
[b]Group:[/b] {path.group()}
[b]Permissions:[/b] {stat.filemode(path.stat().st_mode)}"""


def _get_file_content(path: Path) -> str:
    """Show the path in a notification."""
    try:
        content_bytes = path.read_bytes().replace(b'\0', b'\\x00')
        if len(content_bytes) > FILE_VIEWER_SIZE_LIMIT:
            content_bytes = (
                content_bytes[:FILE_VIEWER_SIZE_LIMIT]
                + (
                    f' [i][{len(content_bytes) - FILE_VIEWER_SIZE_LIMIT} more bytes]'
                    '[/i]'
                ).encode()
            )
    except Exception:  # noqa: BLE001
        report_service_error()
        return '[i][Error reading file content.][/i]'
    else:
        return (
            content_bytes.decode(errors='backslashreplace')
            .replace(
                ' ',
                '[color=#666]󱁐[/color]',
            )
            .replace(
                '\n',
                '[color=#666]󰌑[/color]\n',
            )
            .replace(
                '\t',
                '[color=#666][/color]',
            )
        )


def _open_video(path: Path) -> None:
    """Open the video viewer and start streaming frames."""
    from video_streamer import start_video_stream

    store.dispatch(
        StackPushApplicationAction(application_id='ubo:video-viewer'),
    )
    start_video_stream(path.as_posix())


def _toggle_audio(path: Path) -> None:
    """Toggle audio playback for a file."""
    if _audio_playing[0] == path:
        # Stop playback
        store.dispatch(AudioStopPlaybackAction())
        _audio_playing[0] = None
        _show_file(path)
        return

    # Stop any other playback first
    if _audio_playing[0] is not None:
        store.dispatch(AudioStopPlaybackAction())

    import wave

    try:
        with wave.open(path.as_posix(), 'rb') as wf:
            sample = AudioSample(
                data=wf.readframes(wf.getnframes()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                width=wf.getsampwidth(),
            )
        store.dispatch(AudioPlayAudioSampleAction(sample=sample))
        _audio_playing[0] = path
        _show_file(path)
    except wave.Error:
        _audio_playing[0] = None
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Unsupported Format',
                    content=f'Cannot play {escape_markup(path.name)}.'
                    ' Only WAV files are supported.',
                    icon='󰈔',
                    display_type=NotificationDisplayType.FLASH,
                ),
            ),
        )


def _copy(path: Path) -> None:
    """Copy the path to the clipboard."""

    async def act() -> None:
        destination, _ = await ubo_input(
            title='Copy Destination',
            prompt='Select the destination directory.]\n'
            f'[b]Source:[/b] {escape_markup(path.as_posix())}',
            descriptions=[
                PathInputDescription(
                    selector_config=PathSelectorConfig(
                        accepts_directories=True,
                        accepts_files=False,
                    ),
                ),
            ],
        )

        store.dispatch(
            FileSystemCopyAction(
                sources=[path.as_posix()],
                destination=destination,
            ),
        )

    create_task(act())


def _move(path: Path) -> None:
    """Move the path to the clipboard."""

    async def act() -> None:
        destination, _ = await ubo_input(
            title='Move Destination',
            prompt='Select the destination directory.]\n'
            f'[b]Source:[/b] {escape_markup(path.as_posix())}',
            descriptions=[
                PathInputDescription(
                    selector_config=PathSelectorConfig(
                        accepts_directories=True,
                        accepts_files=False,
                    ),
                ),
            ],
        )

        store.dispatch(
            FileSystemMoveAction(
                sources=[path.as_posix()],
                destination=destination,
            ),
        )

    create_task(act())


def _remove(path: Path) -> None:
    """Remove the path."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title='Confirm Removal',
                content='Are you sure you want to remove '
                f'"{escape_markup(path.as_posix())}"?',
                icon='󰆴',
                display_type=NotificationDisplayType.STICKY,
                dismiss_on_close=True,
                actions=[
                    NotificationDispatchItem(
                        key='confirm',
                        label='Remove',
                        icon='󰆴',
                        store_action=FileSystemRemoveAction(
                            paths=[path.as_posix()],
                        ),
                        close_notification=True,
                    ),
                ],
            ),
        ),
    )


def _file_info_notification_id(path: Path) -> str:
    """Predictable notification ID for file/directory info overlays."""
    return f'file-system:info:{path.as_posix()}'


def _show_directory(path: Path) -> None:
    """Show the path in a notification."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=_file_info_notification_id(path),
                title=escape_markup(path.name),
                content=_file_info(path),
                icon='󰉋',
                display_type=NotificationDisplayType.STICKY,
                show_dismiss_action=False,
                actions=[
                    create_notification_action(
                        key='copy',
                        label='Copy Directory',
                        icon='󰆏',
                        action=functools.partial(_copy, path),
                        close_notification=False,
                    ),
                    create_notification_action(
                        key='move',
                        label='Move Directory',
                        icon='󰉒',
                        action=functools.partial(_move, path),
                        close_notification=False,
                    ),
                    create_notification_action(
                        key='remove',
                        label='Remove Directory',
                        icon='󰉘',
                        action=functools.partial(_remove, path),
                        close_notification=False,
                    ),
                ],
            ),
        ),
    )


def _show_file(path: Path) -> None:
    """Show the path in a notification."""
    file_type, _ = mimetypes.guess_type(path)
    match file_type:
        case str(type_) if type_.startswith('image/'):
            from PIL import Image

            image = Image.open(path)
            width, height = image.size
            image_bytes = image.tobytes()
            view_action = NotificationApplicationItem(
                key='view',
                label='Open Image',
                icon='󰋩',
                application_id='ubo:raw-image-viewer',
                initialization_kwargs={
                    'image': image_bytes,
                    'width': width,
                    'height': height,
                },
                close_notification=False,
            )
        case str(type_) if type_.startswith('audio/'):
            is_playing = _audio_playing[0] == path
            view_action = create_notification_action(
                key='play',
                label='Stop Audio' if is_playing else 'Play Audio',
                icon='󰓛' if is_playing else '󰐊',
                action=functools.partial(_toggle_audio, path),
                close_notification=False,
            )
        case str(type_) if type_.startswith('video/'):
            view_action = create_notification_action(
                key='view',
                label='Play Video',
                icon='󰐊',
                action=functools.partial(_open_video, path),
                close_notification=False,
            )
        case _:
            view_action = NotificationApplicationItem(
                key='view',
                label='View File Content',
                icon='󰦪',
                application_id='ubo:raw-text-viewer',
                initialization_kwargs={
                    'text': _get_file_content(path),
                },
                close_notification=False,
            )

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=_file_info_notification_id(path),
                title=escape_markup(path.name),
                content=_file_info(path),
                icon='󰈔',
                display_type=NotificationDisplayType.STICKY,
                show_dismiss_action=False,
                actions=[
                    view_action,
                    create_notification_action(
                        key='copy',
                        label='Copy File',
                        icon='󰆏',
                        action=functools.partial(_copy, path),
                        close_notification=False,
                    ),
                    create_notification_action(
                        key='move',
                        label='Move File',
                        icon='󰪹',
                        action=functools.partial(_move, path),
                        close_notification=False,
                    ),
                    create_notification_action(
                        key='remove',
                        label='Remove File',
                        icon='󰮘',
                        action=functools.partial(_remove, path),
                        close_notification=False,
                    ),
                ]
                if path.is_file()
                else [],
            ),
        ),
    )


def _cleanup_selector_autoruns() -> None:
    """Unsubscribe selector-mode autoruns and restore browse-mode content.

    For each path that was opened in selector mode, unsubscribe the event
    listener and re-run _items_generator in browse mode to restore "Info" items.
    """
    affected_menu_ids = list(_selector_menu_ids)
    _selector_menu_ids.clear()

    for menu_id in affected_menu_ids:
        if menu_id in _menu_unsubscribers:
            _menu_unsubscribers[menu_id]()
            del _menu_unsubscribers[menu_id]
        # Re-create in browse mode (no accepts_* flags = "Info" button)
        path_str = menu_id.removeprefix('file-system:dir:')
        _items_generator(PathSelectorConfig(initial_path=path_str))


def _select(path: Path) -> None:
    _cleanup_selector_autoruns()
    store.dispatch(FileSystemReportSelectionAction(path=path.as_posix()))


def _get_menu_id_for_path(path: Path) -> str:
    """Get a unique dynamic menu ID for a directory path."""
    return f'file-system:dir:{path.as_posix()}'


def _build_entry_item(
    entry: Path,
    *,
    config: PathSelectorConfig,
    menu_id: str,
    select_directory: _SelectFn | None,
    select_file: _SelectFn | None,
) -> MenuItemData:
    """Build a MenuItemData for a single directory entry."""
    entry_key = entry.as_posix()

    if entry.is_dir():
        action_id = f'file-system:open:{entry_key}'
        _file_browser_action_ids[menu_id].append(action_id)
        register_action(
            action_id,
            functools.partial(
                open_path,
                config=replace(config, initial_path=entry.as_posix()),
            ),
            allow_reregister=True,
        )
        return MenuItemData(
            key=entry_key,
            label=escape_markup(entry.name),
            icon='󰉋',
            background_color='#303030' if select_directory is None else None,
            action_id=action_id,
        )

    if select_file:
        is_grayed = config.acceptable_suffixes and not any(
            suffix in config.acceptable_suffixes for suffix in entry.suffixes
        )
        action_id = f'file-system:file:{entry_key}'
        _file_browser_action_ids[menu_id].append(action_id)
        register_action(
            action_id,
            functools.partial(select_file, entry),
            allow_reregister=True,
        )
        return MenuItemData(
            key=entry_key,
            label=escape_markup(entry.name),
            icon='󰈔',
            background_color='#303030' if is_grayed else None,
            action_id=action_id,
        )

    return MenuItemData(
        key=entry_key,
        label=escape_markup(entry.name),
        icon='󰈔',
        background_color='#303030',
    )


def _resolve_select_handlers(
    config: PathSelectorConfig,
) -> tuple[_SelectFn | None, _SelectFn | None]:
    """Determine the select/show handlers based on config mode."""
    if config.accepts_directories and config.accepts_files:
        return _select, _select
    if config.accepts_directories:
        return _select, None
    if config.accepts_files:
        return None, _select
    return _show_directory, _show_file


def _items_generator(config: PathSelectorConfig) -> None:  # noqa: C901
    path = Path(config.initial_path) if config.initial_path else Path('/')
    menu_id = _get_menu_id_for_path(path)
    select_directory, select_file = _resolve_select_handlers(config)

    # Clean up existing autorun for this menu_id to avoid competing autoruns
    if menu_id in _menu_unsubscribers:
        _menu_unsubscribers[menu_id]()
        del _menu_unsubscribers[menu_id]

    def _dir_mtime() -> float:
        """Return directory mtime — cheap single syscall for change detection."""
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    @store.autorun(lambda _: _dir_mtime())
    def items(_: float) -> None:
        # Clean up old actions
        for action_id in _file_browser_action_ids.get(menu_id, []):
            unregister_action(action_id)
        _file_browser_action_ids[menu_id] = []

        menu_items: list[MenuItemData] = []

        # "Select" or "Info" button for current directory
        if select_directory:
            select_action_id = f'file-system:select:{path.as_posix()}'
            _file_browser_action_ids[menu_id].append(select_action_id)
            register_action(
                select_action_id,
                functools.partial(select_directory, path),
                allow_reregister=True,
            )
            menu_items.append(
                MenuItemData(
                    key='select',
                    label='[b]Select[/b]'
                    if config.accepts_directories
                    else '[b]Info[/b]',
                    icon='',
                    background_color='#2d5b86',
                    action_id=select_action_id,
                ),
            )

        # Directory contents
        try:
            entries = sorted(
                path.iterdir(),
                key=lambda x: x.name.lower(),
            )
        except (PermissionError, OSError):
            entries = []

        for entry in entries:
            if not config.show_hidden and entry.name.startswith('.'):
                continue
            menu_items.append(
                _build_entry_item(
                    entry,
                    config=config,
                    menu_id=menu_id,
                    select_directory=select_directory,
                    select_file=select_file,
                ),
            )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=menu_id,
                title=escape_markup(path.as_posix()),
                items=tuple(menu_items),
            ),
        )

    items()
    # Subscribe to FileSystemEvent for immediate refresh on in-app operations
    event_unsub = store.subscribe_event(FileSystemEvent, items)
    # Chain autorun unsubscriber + event unsubscriber
    autorun_unsub = items.unsubscribe

    def _combined_unsub() -> None:
        autorun_unsub()
        event_unsub()

    _menu_unsubscribers[menu_id] = _combined_unsub

    # Track selector-mode menu_ids so they can be cleaned up on select
    is_selector_mode = bool(config.accepts_directories or config.accepts_files)
    if is_selector_mode and menu_id not in _selector_menu_ids:
        _selector_menu_ids.append(menu_id)


def open_path(*, config: PathSelectorConfig | None = None) -> None:
    """Open a directory and show its contents as a dynamic menu."""
    config = config or PathSelectorConfig()
    path = Path(config.initial_path) if config.initial_path else Path('/')
    menu_id = _get_menu_id_for_path(path)

    try:
        if path.is_dir():
            _items_generator(config)
            store.dispatch(StackPushMenuAction(menu_key=menu_id))
            if config.accepts_directories or config.accepts_files:
                store.dispatch(FileSystemSelectorPushedAction())
            return
    except PermissionError:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Permission Denied',
                    content=f'Cannot access {escape_markup(path.as_posix())}.',
                    icon='󰍛',
                    display_type=NotificationDisplayType.FLASH,
                ),
            ),
        )
        return
    except Exception:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Error',
                    content='An error occurred while accessing '
                    f'{escape_markup(path.as_posix())}',
                    icon='󰍛',
                    display_type=NotificationDisplayType.FLASH,
                ),
            ),
        )
        raise

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title='Invalid Selection',
                content=f'{escape_markup(path.as_posix())} is not a directory.',
                icon='󰍛',
                display_type=NotificationDisplayType.FLASH,
            ),
        ),
    )

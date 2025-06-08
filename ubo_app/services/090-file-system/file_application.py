"""Implementation of a file system navigation application."""

from __future__ import annotations

import functools
import stat
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from kivy.utils import escape_markup
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadlessMenu

from ubo_app.store.main import store
from ubo_app.store.services.file_system import (
    FileSystemEvent,
    FileSystemReportSelectionAction,
    PathSelectorConfig,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationApplicationItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.file_system import human_readable_size

if TYPE_CHECKING:
    from collections.abc import Callable

FILE_VIEWER_SIZE_LIMIT = 2**11  # 2 KiB


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
                '[color=#666][/color]',
            )
        )


def _show_directory(path: Path) -> HeadlessMenu | None:
    """Show the path in a notification."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title=escape_markup(path.name),
                content=_file_info(path),
                icon='󰉋',
                display_type=NotificationDisplayType.STICKY,
                show_dismiss_action=False,
                actions=[],
            ),
        ),
    )


def _show_file(path: Path) -> HeadlessMenu | None:
    """Show the path in a notification."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title=escape_markup(path.name),
                content=_file_info(path),
                icon='󰈔',
                display_type=NotificationDisplayType.STICKY,
                show_dismiss_action=False,
                actions=[
                    NotificationApplicationItem(
                        key='view',
                        label='View File Content',
                        icon='󰦪',
                        application_id='ubo:raw-content-viewer',
                        initialization_kwargs={
                            'text': _get_file_content(path),
                        },
                        close_notification=False,
                    ),
                ]
                if path.is_file()
                else [],
            ),
        ),
    )


def _select(path: Path) -> None:
    store.dispatch(FileSystemReportSelectionAction(path=path))


def _items_generator(config: PathSelectorConfig) -> Callable[[], list[ActionItem]]:
    path = config.initial_path or Path('/')
    if config.accepts_directories and config.accepts_files:
        select_directory = select_file = _select
    elif config.accepts_directories:
        select_directory = _select
        select_file = None
    elif config.accepts_files:
        select_directory = None
        select_file = _select
    else:
        select_directory = _show_directory
        select_file = _show_file

    @store.autorun(lambda _: None, options=AutorunOptions(memoization=False))
    def items(_: None) -> list[ActionItem]:
        return (
            [
                ActionItem(
                    key='select',
                    label='[b]Select[/b]'
                    if config.accepts_directories
                    else '[b]Info[/b]',
                    icon='',
                    background_color='#2d5b86',
                    action=functools.partial(select_directory, path),
                ),
            ]
            if select_directory
            else []
        ) + [
            ActionItem(
                key=item.as_posix(),
                label=escape_markup(item.name),
                background_color='#303030'
                if (item.is_dir() and select_directory is None)
                or (
                    item.is_file()
                    and (
                        select_file is None
                        or (
                            config.acceptable_suffixes
                            and not any(
                                suffix in config.acceptable_suffixes
                                for suffix in item.suffixes
                            )
                        )
                    )
                )
                else None,
                icon='󰈔' if item.is_file() else '󰉋',
                action=functools.partial(
                    open_path,
                    config=replace(config, initial_path=item),
                ),
            )
            for item in sorted(
                path.iterdir(),
                key=lambda x: x.name.lower(),
            )
            if config.show_hidden or not item.name.startswith('.')
        ]

    store.subscribe_event(FileSystemEvent, items)

    return items


def open_path(*, config: PathSelectorConfig | None = None) -> HeadlessMenu | None:
    """Open a directory and return a HeadlessMenu for its contents."""
    config = config or PathSelectorConfig()
    path = config.initial_path or Path('/')

    try:
        if path.is_dir():
            return HeadlessMenu(
                title=escape_markup(path.as_posix()),
                items=_items_generator(config),
            )
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
        return None
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
    else:
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
        return None

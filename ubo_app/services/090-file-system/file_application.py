"""Implementation of a file system navigation application."""

from __future__ import annotations

import functools
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from kivy.utils import escape_markup
from ubo_gui.menu.menu_widget import MenuPageWidget
from ubo_gui.menu.types import ActionItem, HeadlessMenu, Item

from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Notification,
    NotificationApplicationItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.file_system import human_readable_size

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.services.file_system import PathSelectorConfig

SELECT_NOTIFICATION_ID = 'file_system:select'
FILE_SIZE_LIMIT = 2**13  # 8 KiB


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
[b]Path:[/b] {path.as_posix()}
[b]Size:[/b] {'-' if path.is_dir() else human_readable_size(path.stat().st_size)}
[b]Owner:[/b] {path.owner()}
[b]Group:[/b] {path.group()}
[b]Permissions:[/b] {stat.filemode(path.stat().st_mode)}"""


class PathSelectorApplication(MenuPageWidget):
    """A class to represent a file system navigation application."""

    def __init__(
        self,
        config: PathSelectorConfig,
        items: Sequence[Item] | None = None,
        *args: object,
        **kwargs: object,
    ) -> None:
        """Initialize the PathSelectorApplication."""
        super().__init__(*args, **kwargs, items=items)
        self.config = config

    def _get_file_content(
        self,
        path: Path,
    ) -> str:
        """Show the path in a notification."""
        try:
            content_bytes = path.read_bytes().replace(b'\0', b'\\x00')
            if len(content_bytes) > FILE_SIZE_LIMIT:
                content_bytes = (
                    content_bytes[:FILE_SIZE_LIMIT]
                    + (
                        f' [i][{len(content_bytes) - FILE_SIZE_LIMIT} more bytes][/i]'
                    ).encode()
                )
        except Exception:  # noqa: BLE001
            report_service_error()
            return '[i][Error reading file content.][/i]'
        else:
            return content_bytes.decode(errors='backslashreplace')

    def show_directory(
        self,
        path: Path,
    ) -> HeadlessMenu | None:
        """Show the path in a notification."""
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=SELECT_NOTIFICATION_ID,
                    title=path.name,
                    content=_file_info(path),
                    icon='󰉋',
                    display_type=NotificationDisplayType.STICKY,
                    show_dismiss_action=False,
                ),
            ),
        )

    def show_file(self, path: Path) -> HeadlessMenu | None:
        """Show the path in a notification."""
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=SELECT_NOTIFICATION_ID,
                    title=path.name,
                    content=_file_info(path),
                    icon='󰦪',
                    display_type=NotificationDisplayType.STICKY,
                    show_dismiss_action=False,
                    actions=[
                        NotificationApplicationItem(
                            key='view',
                            label='View File Content',
                            icon='󰦪',
                            application_id='ubo:raw-content-viewer',
                            initialization_kwargs={
                                'text': self._get_file_content(path),
                            },
                            close_notification=False,
                        ),
                    ]
                    if path.is_file()
                    else [],
                ),
            ),
        )

    def open(self, *, path: Path | None = None) -> HeadlessMenu | None:
        """Open a directory and return a HeadlessMenu for its contents."""
        path = path or self.config.initial_path or Path('/')
        select_directory = select_file = None
        is_selecting = self.config.accepts_directories or self.config.accepts_files
        if not is_selecting:
            select_directory = self.show_directory
            select_file = self.show_file
        elif self.config.accepts_directories:
            select_directory = self.show_directory
        elif self.config.accepts_files:
            select_file = self.show_file
        try:
            if path.is_dir():
                return HeadlessMenu(
                    title=path.as_posix(),
                    items=[
                        ActionItem(
                            key='select',
                            label='Select',
                            icon='',
                            background_color='#2d5b86',
                            action=functools.partial(select_directory, path)
                            if select_directory
                            else lambda: None,
                        ),
                    ]
                    + [
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
                                        self.config.acceptable_suffixes
                                        and not any(
                                            suffix in self.config.acceptable_suffixes
                                            for suffix in item.suffixes
                                        )
                                    )
                                )
                            )
                            else None,
                            icon='󰈔' if item.is_file() else '󰉋',
                            action=functools.partial(self.open, path=item),
                        )
                        for item in sorted(
                            path.iterdir(),
                            key=lambda x: x.name.lower(),
                        )
                        if self.config.show_hidden or not item.name.startswith('.')
                    ],
                )
            if path.is_file():
                if select_file:
                    return select_file(path)
                return None
        except PermissionError:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Permission Denied',
                        content=f'Cannot access {path.as_posix()}.',
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
                        content=f'An error occurred while accessing {path.as_posix()}',
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
                        content=f'{path.as_posix()} is neither a file nor a directory.',
                        icon='󰍛',
                        display_type=NotificationDisplayType.FLASH,
                    ),
                ),
            )
            return None

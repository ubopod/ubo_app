"""Setup module for initializing the File System application."""

from __future__ import annotations

import functools

from constants import SELECTOR_APPLICATION_ID
from file_application import open_path

from ubo_app.store.core.callback_registry import register_auto_callback
from ubo_app.store.core.types import RegisterRegularAppAction
from ubo_app.store.input.types import InputCancelAction
from ubo_app.store.main import store
from ubo_app.store.services.file_system import (
    FileSystemCopyEvent,
    FileSystemMoveEvent,
    FileSystemRemoveEvent,
    FileSystemSelectEvent,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsAddAction,
)


def init_service() -> None:
    """Initialize the service by registering the File System application."""
    from ubo_app.store.core.action_registry import register_action

    register_action('file-system:open', open_path)
    store.dispatch(
        RegisterRegularAppAction(
            label='File System',
            icon='󰉋',
            action_id='file-system:open',
            key='file-system',
        ),
    )

    def handle_open_path_event(event: FileSystemSelectEvent) -> None:
        """Open the file system path selector."""
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=SELECTOR_APPLICATION_ID.format(id=event.description.id),
                    title=event.description.title or 'Select Path',
                    content=event.description.prompt or 'Please select a path to open.',
                    icon='󰉋',
                    display_type=NotificationDisplayType.STICKY,
                    show_dismiss_action=False,
                    on_close_id=register_auto_callback(
                        functools.partial(
                            store.dispatch,
                            InputCancelAction(id=event.description.id),
                        ),
                    ),
                    actions=[
                        NotificationActionItem(
                            key='open-path',
                            label='Open Path Selector',
                            icon='󰉋',
                            close_notification=False,
                            action=functools.partial(
                                open_path,
                                config=event.description.selector_config,
                            ),
                        ),
                    ],
                ),
            ),
        )

    def handle_copy_event(event: FileSystemCopyEvent) -> None:
        from pathlib import Path
        from shutil import copyfile, copytree

        destination = Path(event.destination)
        for source_str in event.sources:
            source = Path(source_str)
            if source.is_dir():
                copytree(source, destination / source.name)
            else:
                copyfile(source, destination / source.name)

    def handle_move_event(event: FileSystemMoveEvent) -> None:
        from pathlib import Path
        from shutil import move

        destination = Path(event.destination)
        for source_str in event.sources:
            source = Path(source_str)
            move(source, destination / source.name)

    def handle_remove_event(event: FileSystemRemoveEvent) -> None:
        from pathlib import Path
        from shutil import rmtree

        for path_str in event.paths:
            source = Path(path_str)
            if source.is_dir():
                rmtree(source)
            else:
                source.unlink(missing_ok=True)

    store.subscribe_event(FileSystemSelectEvent, handle_open_path_event)
    store.subscribe_event(FileSystemCopyEvent, handle_copy_event)
    store.subscribe_event(FileSystemMoveEvent, handle_move_event)
    store.subscribe_event(FileSystemRemoveEvent, handle_remove_event)

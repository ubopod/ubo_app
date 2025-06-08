"""Setup module for initializing the File System application."""

from __future__ import annotations

import functools

from constants import SELECTOR_APPLICATION_ID
from file_application import open_path
from ubo_gui.menu.types import ActionItem

from ubo_app.store.core.types import RegisterRegularAppAction
from ubo_app.store.input.types import InputCancelAction
from ubo_app.store.main import store
from ubo_app.store.services.file_system import FileSystemSelectEvent
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsAddAction,
)


def init_service() -> None:
    """Initialize the service by registering the File System application."""
    store.dispatch(
        RegisterRegularAppAction(
            menu_item=ActionItem(
                label='File System',
                icon='󰉋',
                action=open_path,
            ),
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
                    on_close=functools.partial(
                        store.dispatch,
                        InputCancelAction(id=event.description.id),
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

    store.subscribe_event(FileSystemSelectEvent, handle_open_path_event)

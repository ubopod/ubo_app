"""Setup module for initializing the File System application."""

from __future__ import annotations

import functools

from constants import SELECTOR_APPLICATION_ID
from file_application import (
    _cleanup_selector_autoruns,
    _file_info_notification_id,
    open_path,
)

from ubo_app.store.core.callback_registry import register_auto_callback
from ubo_app.store.core.types import RegisterRegularAppAction
from ubo_app.store.input.types import InputCancelAction
from ubo_app.store.main import store
from ubo_app.store.services.file_download import FileDownloadRequestEvent
from ubo_app.store.services.file_system import (
    FileSystemCopyEvent,
    FileSystemMoveEvent,
    FileSystemRemoveEvent,
    FileSystemSelectEvent,
    FileSystemSelectorCleanupEvent,
)
from ubo_app.store.services.file_upload import (
    FileUploadChunkEvent,
    FileUploadCompleteEvent,
    FileUploadStartEvent,
)
from ubo_app.store.services.notification_helpers import create_notification_action
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)
from ubo_app.utils.async_ import create_task


async def _deferred_selector_cleanup() -> None:
    """Run selector cleanup outside the dispatch cycle."""
    _cleanup_selector_autoruns()


def _file_system_path_matcher(path: tuple[str, ...]) -> str | None:
    """Match file system navigation paths to dynamic menu IDs."""
    for element in reversed(path):
        if element.startswith('file-system:dir:'):
            return element
    return None


def init_service() -> None:  # noqa: C901, PLR0915
    """Initialize the service by registering the File System application."""
    from ubo_app.store.core.action_registry import register_action
    from ubo_app.store.core.view_registry import register_path_menu_matcher

    register_path_menu_matcher('file-system:paths', _file_system_path_matcher)

    register_action('file-system:open', open_path)
    store.dispatch(
        RegisterRegularAppAction(
            label='File System',
            icon='󰉋',
            action_id='file-system:open',
            key='file-system',
            app_category='Files',
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
                        create_notification_action(
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

        from ubo_app.logger import logger

        destination = Path(event.destination)
        if not destination.is_dir():
            logger.error(
                'Copy destination does not exist',
                extra={'destination': event.destination},
            )
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Copy Failed',
                        content=f'Destination does not exist:'
                        f' {destination.as_posix()}',
                        icon='󰅙',
                        display_type=NotificationDisplayType.FLASH,
                        dismiss_on_close=True,
                    ),
                ),
            )
            return

        names = []
        for source_str in event.sources:
            source = Path(source_str)
            try:
                if source.is_dir():
                    copytree(source, destination / source.name)
                else:
                    copyfile(source, destination / source.name)
            except Exception:
                logger.exception(
                    'Failed to copy',
                    extra={
                        'source': source_str,
                        'destination': event.destination,
                    },
                )
                store.dispatch(
                    NotificationsAddAction(
                        notification=Notification(
                            title='Copy Failed',
                            content=f'Failed to copy {source.name}',
                            icon='󰅙',
                            display_type=NotificationDisplayType.FLASH,
                            dismiss_on_close=True,
                        ),
                    ),
                )
                return
            names.append(source.name)

        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Copied',
                    content=f'{", ".join(names)} copied to'
                    f' {destination.as_posix()}',
                    icon='󰆏',
                    display_type=NotificationDisplayType.FLASH,
                    dismiss_on_close=True,
                ),
            ),
        )
    def handle_move_event(event: FileSystemMoveEvent) -> None:
        from pathlib import Path
        from shutil import move

        from ubo_app.logger import logger

        destination = Path(event.destination)
        if not destination.is_dir():
            logger.error(
                'Move destination does not exist',
                extra={'destination': event.destination},
            )
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        title='Move Failed',
                        content=f'Destination does not exist:'
                        f' {destination.as_posix()}',
                        icon='󰅙',
                        display_type=NotificationDisplayType.FLASH,
                        dismiss_on_close=True,
                    ),
                ),
            )
            return

        names = []
        for source_str in event.sources:
            source = Path(source_str)
            try:
                move(source, destination / source.name)
            except Exception:
                logger.exception(
                    'Failed to move',
                    extra={
                        'source': source_str,
                        'destination': event.destination,
                    },
                )
                store.dispatch(
                    NotificationsAddAction(
                        notification=Notification(
                            title='Move Failed',
                            content=f'Failed to move {source.name}',
                            icon='󰅙',
                            display_type=NotificationDisplayType.FLASH,
                            dismiss_on_close=True,
                        ),
                    ),
                )
                return
            names.append(source.name)
            store.dispatch(
                NotificationsClearByIdAction(
                    id=_file_info_notification_id(source),
                ),
            )

        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Moved',
                    content=f'{", ".join(names)} moved to'
                    f' {destination.as_posix()}',
                    icon='󰉒',
                    display_type=NotificationDisplayType.FLASH,
                    dismiss_on_close=True,
                ),
            ),
        )

    def handle_remove_event(event: FileSystemRemoveEvent) -> None:
        from pathlib import Path
        from shutil import rmtree

        from ubo_app.logger import logger

        names = []
        for path_str in event.paths:
            source = Path(path_str)
            try:
                if source.is_dir():
                    rmtree(source)
                else:
                    source.unlink(missing_ok=True)
            except Exception:
                logger.exception(
                    'Failed to remove',
                    extra={'path': path_str},
                )
                store.dispatch(
                    NotificationsAddAction(
                        notification=Notification(
                            title='Remove Failed',
                            content=f'Failed to remove {source.name}',
                            icon='󰅙',
                            display_type=NotificationDisplayType.FLASH,
                            dismiss_on_close=True,
                        ),
                    ),
                )
                return
            names.append(source.name)
            store.dispatch(
                NotificationsClearByIdAction(
                    id=_file_info_notification_id(source),
                ),
            )

        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Removed',
                    content=f'{", ".join(names)} removed',
                    icon='󰆴',
                    display_type=NotificationDisplayType.FLASH,
                    dismiss_on_close=True,
                ),
            ),
        )

    from upload_handler import (
        handle_upload_chunk,
        handle_upload_complete,
        handle_upload_start,
    )
    from video_streamer import register_video_stream_cleanup

    store.subscribe_event(FileSystemSelectEvent, handle_open_path_event)
    store.subscribe_event(FileSystemCopyEvent, handle_copy_event)
    store.subscribe_event(FileSystemMoveEvent, handle_move_event)
    store.subscribe_event(FileSystemRemoveEvent, handle_remove_event)
    store.subscribe_event(
        FileSystemSelectorCleanupEvent,
        lambda _: create_task(_deferred_selector_cleanup()),
    )
    store.subscribe_event(FileUploadStartEvent, handle_upload_start)
    store.subscribe_event(FileUploadChunkEvent, handle_upload_chunk)
    store.subscribe_event(FileUploadCompleteEvent, handle_upload_complete)

    from download_handler import handle_download_request

    store.subscribe_event(FileDownloadRequestEvent, handle_download_request)
    register_video_stream_cleanup()

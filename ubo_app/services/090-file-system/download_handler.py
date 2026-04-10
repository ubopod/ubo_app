"""Server-side download handler: prepares files for browser download."""

from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.file_download import FileDownloadReadyAction
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.file_download import register_download

if TYPE_CHECKING:
    from ubo_app.store.services.file_download import FileDownloadRequestEvent


def _download_notification_id(token: str) -> str:
    return f'file-system:download:{token}'


def handle_download_request(event: FileDownloadRequestEvent) -> None:
    """Prepare a file or directory for download."""
    path = Path(event.path)

    if not path.exists():
        logger.error(
            'Download path does not exist',
            extra={'path': event.path},
        )
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=f'file-system:download-error:{event.path}',
                    title='Download Failed',
                    content=f'Path does not exist: {event.path}',
                    icon='󰅙',
                    display_type=NotificationDisplayType.FLASH,
                    dismiss_on_close=True,
                ),
            ),
        )
        return

    token = uuid4().hex

    if path.is_dir():
        # Show progress notification for zipping
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=_download_notification_id(token),
                    title='Preparing Download',
                    content=f'Zipping {path.name}...',
                    icon='󰇚',
                    display_type=NotificationDisplayType.STICKY,
                    progress=math.nan,
                    show_dismiss_action=False,
                ),
            ),
        )

        # Create zip archive in temp directory
        temp_dir = tempfile.mkdtemp(prefix='ubo_download_')
        archive_base = str(Path(temp_dir) / path.name)
        archive_path = shutil.make_archive(archive_base, 'zip', path)
        filename = f'{path.name}.zip'

        register_download(token, archive_path, filename, is_temp=True)

        logger.info(
            'Directory zipped for download',
            extra={
                'path': event.path,
                'archive_path': archive_path,
                'token': token,
            },
        )
    else:
        filename = path.name
        register_download(token, str(path), filename, is_temp=False)

        logger.info(
            'File prepared for download',
            extra={
                'path': event.path,
                'token': token,
            },
        )

    # Update notification to indicate readiness
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=_download_notification_id(token),
                title='Download Ready',
                content=f'{filename} is ready for download in Web UI',
                icon='󰇚',
                display_type=NotificationDisplayType.FLASH,
                dismiss_on_close=True,
            ),
        ),
    )

    # Signal the web UI that the download is ready
    store.dispatch(
        FileDownloadReadyAction(
            download_token=token,
            filename=filename,
        ),
    )

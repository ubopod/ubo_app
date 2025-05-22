"""Utilities for downloading and extracting the piper model."""

from __future__ import annotations

import shutil
from functools import reduce
from typing import TYPE_CHECKING

import aiostream
from constants import (
    PIPER_DOWNLOAD_NOTIFICATION_ID,
    PIPER_MODEL_JSON_PATH,
    PIPER_MODEL_PATH,
    PIPER_MODEL_URL,
)

from ubo_app.colors import DANGER_COLOR, INFO_COLOR
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils.async_ import create_task
from ubo_app.utils.download import download_file

if TYPE_CHECKING:
    from collections.abc import Callable


def _update_download_notification(*, progress: float) -> None:
    extra_information = ReadableInformation(
        text="""\
The download progress is shown in the radial progress bar at the top left corner of \
the screen.""",
    )
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=PIPER_DOWNLOAD_NOTIFICATION_ID,
                title='Downloading',
                content='Piper speech synthesis model',
                extra_information=extra_information,
                display_type=NotificationDisplayType.FLASH
                if progress == 1
                else NotificationDisplayType.STICKY,
                flash_time=1,
                color=INFO_COLOR,
                icon='󰇚',
                blink=False,
                progress=progress,
                show_dismiss_action=progress == 1,
                dismiss_on_close=progress == 1,
            ),
        ),
    )


def _handle_error() -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=PIPER_DOWNLOAD_NOTIFICATION_ID,
                title='Piper',
                content='Failed to download',
                display_type=NotificationDisplayType.STICKY,
                color=DANGER_COLOR,
                icon='󰜺',
                chime=Chime.FAILURE,
            ),
        ),
    )
    shutil.rmtree(PIPER_MODEL_PATH, ignore_errors=True)


def download_piper_model(*, callback: Callable[[], None]) -> None:
    """Download Piper model."""
    shutil.rmtree(PIPER_MODEL_PATH, ignore_errors=True)

    _update_download_notification(progress=0)

    async def act() -> None:
        try:
            PIPER_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

            async for download_report in aiostream.stream.ziplatest(
                download_file(url=PIPER_MODEL_URL, path=PIPER_MODEL_PATH),
                download_file(
                    url=f'{PIPER_MODEL_URL}.json',
                    path=PIPER_MODEL_JSON_PATH,
                ),
                default=(0, None),
            ):
                downloaded_bytes, size = reduce(
                    lambda accumulator, report: (
                        report[0] + accumulator[0],
                        (report[1] or 1024**2) + accumulator[1],
                    )
                    if report
                    else accumulator,
                    download_report,
                    (0, 0),
                )
                if size:
                    _update_download_notification(
                        progress=min(1.0, downloaded_bytes / size),
                    )

            _update_download_notification(progress=1.0)
            callback()
        except Exception:
            _handle_error()
            raise

    create_task(act())

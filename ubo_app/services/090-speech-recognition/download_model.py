"""Utilities for downloading and extracting the Vosk model."""

from __future__ import annotations

import asyncio
import shutil

from constants import (
    VOSK_DOWNLOAD_NOTIFICATION_ID,
    VOSK_DOWNLOAD_PATH,
    VOSK_MODEL_PATH,
    VOSK_MODEL_URL,
)

from ubo_app.colors import DANGER_COLOR, INFO_COLOR
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionSetIsIntentsActiveAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils.async_ import create_task
from ubo_app.utils.download import download_file


def _update_download_notification(*, progress: float) -> None:
    extra_information = ReadableInformation(
        text="""\
The download progress is shown in the radial progress bar at the top left corner of \
the screen.""",
    )
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=VOSK_DOWNLOAD_NOTIFICATION_ID,
                title='Downloading',
                content='Vosk speech recognition model',
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
                id=VOSK_DOWNLOAD_NOTIFICATION_ID,
                title='Vosk',
                content='Failed to download',
                display_type=NotificationDisplayType.STICKY,
                color=DANGER_COLOR,
                icon='󰜺',
                chime=Chime.FAILURE,
            ),
        ),
    )
    shutil.rmtree(VOSK_MODEL_PATH, ignore_errors=True)


def download_vosk_model() -> None:
    """Download Vosk model."""
    shutil.rmtree(VOSK_MODEL_PATH, ignore_errors=True)

    _update_download_notification(progress=0)

    async def act() -> None:
        try:
            VOSK_DOWNLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
            VOSK_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

            async for downloaded_bytes, size in download_file(
                url=VOSK_MODEL_URL,
                path=VOSK_DOWNLOAD_PATH,
            ):
                if size:
                    _update_download_notification(
                        progress=min(1.0, downloaded_bytes / size),
                    )

            _update_download_notification(progress=1.0)

            process = await asyncio.create_subprocess_exec(
                '/usr/bin/env',
                'unzip',
                '-o',
                VOSK_DOWNLOAD_PATH,
                '-d',
                VOSK_MODEL_PATH.parent,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
            store.dispatch(SpeechRecognitionSetIsIntentsActiveAction(is_active=True))
        except Exception:
            _handle_error()
            raise
        finally:
            VOSK_DOWNLOAD_PATH.unlink(missing_ok=True)

    create_task(act())

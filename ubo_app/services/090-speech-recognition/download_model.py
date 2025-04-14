"""Utilities for downloading and extracting the Vosk model."""

from __future__ import annotations

import asyncio
import shutil

import aiofiles
import aiohttp
from constants import (
    VOSK_DOWNLOAD_NOTIFICATION_ID,
    VOSK_DOWNLOAD_PATH,
    VOSK_MODEL_PATH,
    VOSK_MODEL_URL,
)

from ubo_app.colors import DANGER_COLOR, INFO_COLOR
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_recognition import SpeechRecognitionSetIsActiveAction
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils.async_ import create_task


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
                title=f'Downloading - {progress:.1%}',
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
            downloaded_bytes = 0
            async with (
                aiohttp.ClientSession() as session,
                session.get(VOSK_MODEL_URL, raise_for_status=True) as response,
            ):
                total_size_header = response.headers.get('Content-Length')
                if total_size_header:
                    try:
                        total_size = int(total_size_header)
                        if total_size <= 0:
                            logger.warning(
                                'Vosk: Invalid Content-Length header',
                                extra={'header': total_size_header},
                            )
                            total_size = None
                    except ValueError:
                        logger.warning(
                            'Vosk: Invalid Content-Length header',
                            extra={'header': total_size_header},
                        )
                        total_size = None
                else:
                    logger.warning('Vosk: No Content-Length header')
                    total_size = None

                async with aiofiles.open(VOSK_DOWNLOAD_PATH, mode='wb') as f:
                    async for chunk in response.content.iter_chunked(1024 * 16):
                        await f.write(chunk)
                        downloaded_bytes += len(chunk)

                        if total_size:
                            progress = min(downloaded_bytes / total_size, 1.0)
                            _update_download_notification(progress=progress)

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
            store.dispatch(SpeechRecognitionSetIsActiveAction(is_active=True))
        except Exception:
            _handle_error()
            raise
        finally:
            VOSK_DOWNLOAD_PATH.unlink(missing_ok=True)

    create_task(act())

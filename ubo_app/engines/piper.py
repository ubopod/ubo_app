"""Piper engine interface."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from functools import reduce

import aiostream
from typing_extensions import override
from ubo_gui.constants import WARNING_COLOR

from ubo_app.colors import DANGER_COLOR, INFO_COLOR
from ubo_app.constants.assistant import (
    PIPER_DOWNLOAD_NOTIFICATION_ID,
    PIPER_MODEL_HASH,
    PIPER_MODEL_JSON_PATH,
    PIPER_MODEL_PATH,
    PIPER_MODEL_URL,
)
from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.store.main import store
from ubo_app.store.services.assistant import AssistantUpdateProvidersAction
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils.async_ import create_task
from ubo_app.utils.download import download_file


class PiperEngine(NeedsSetupMixin, AIProviderMixin):
    """Piper engine."""

    @property
    def name(self) -> str:
        """The internal name of the Piper engine."""
        return 'piper'

    @property
    def label(self) -> str:
        """The display label for the Piper engine."""
        return 'Piper'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the Piper service API key is not set."""
        return 'Piper model path does not exist. Please download it in the settings.'

    def _update_download_notification(self, *, progress: float) -> None:
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

    def _handle_error(self) -> None:
        from ubo_app.store.main import store

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

    def _download_piper_model(self) -> None:
        """Download Piper model."""
        shutil.rmtree(PIPER_MODEL_PATH, ignore_errors=True)

        self._update_download_notification(progress=0)

        async def download() -> None:
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
                        self._update_download_notification(
                            progress=min(1.0, downloaded_bytes / size),
                        )

                self._update_download_notification(progress=1.0)
                store.dispatch(
                    AssistantUpdateProvidersAction(),
                )
            except Exception:
                self._handle_error()
                raise
            finally:
                self.event.set()

        create_task(download())

    @override
    async def _setup(self) -> None:
        if self.is_setup:
            return
        from ubo_app.store.main import store

        self.event = asyncio.Event()
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Piper Engine Setup',
                    content='Download the Piper model.',
                    color=WARNING_COLOR,
                    actions=[
                        NotificationActionItem(
                            label='Download Model',
                            icon='󰇚',
                            action=self._download_piper_model,
                        ),
                    ],
                ),
            ),
        )
        await self.event.wait()

    @property
    @override
    def is_setup(self) -> bool:
        if not PIPER_MODEL_PATH.exists() or not PIPER_MODEL_JSON_PATH.exists():
            return False

        with PIPER_MODEL_JSON_PATH.open('r') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                return False
            else:
                if data['dataset'] != 'kristin':
                    return False

        # check checksum
        with PIPER_MODEL_PATH.open('rb') as f:
            sha256_hash = hashlib.sha256()

            for chunk in iter(lambda: f.read(4096), b''):
                sha256_hash.update(chunk)

            if sha256_hash.hexdigest() != PIPER_MODEL_HASH:
                return False

        return True

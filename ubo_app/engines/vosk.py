"""Vosk engine interface."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from typing_extensions import override

from ubo_app.colors import DANGER_COLOR, INFO_COLOR, WARNING_COLOR
from ubo_app.constants.assistant import VOSK_DOWNLOAD_NOTIFICATION_ID
from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.vosk_catalog import (
    DEFAULT_VOSK_MODEL_ID,
    VOSK_LANGUAGES,
    download_url_for,
    model_for,
    model_path_for,
)
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantSetVoskDownloadedModelsAction,
    AssistantUpdateProvidersAction,
)
from ubo_app.store.services.notification_helpers import create_notification_action
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionSetSlotEnabledAction,
    WakeMode,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils.async_ import create_task
from ubo_app.utils.download import download_file

if TYPE_CHECKING:
    from collections.abc import Callable


def _model_dir(model_id: str) -> Path:
    return Path(str(model_path_for(model_id)))


def _download_zip(model_id: str) -> Path:
    return _model_dir(model_id).with_suffix('.zip')


def _model_is_setup(model_id: str) -> bool:
    """Return True iff *model_id* has been extracted to disk."""
    return _model_dir(model_id).exists()


@store.with_state(lambda state: state.assistant.selected_vosk_model)
def _read_selected_model(selected_model: str) -> str:
    """Read the user's currently selected Vosk model id from the store."""
    return selected_model or DEFAULT_VOSK_MODEL_ID


class VoskEngine(NeedsSetupMixin, AIProviderMixin):
    """Vosk engine."""

    @property
    def name(self) -> str:
        """The internal name of the Vosk engine."""
        return 'vosk'

    @property
    def label(self) -> str:
        """The display label for the Vosk engine."""
        return 'Vosk'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the selected Vosk model is missing."""
        return 'Vosk model not found. Pick a model in Settings to download it.'

    @property
    @override
    @store.with_state(lambda state: state.assistant.selected_vosk_model)
    def is_setup(  # noqa: PLR0206
        self,
        selected_model: str,
    ) -> bool:
        """Return True iff the currently selected Vosk model exists on disk."""
        model_id = selected_model or DEFAULT_VOSK_MODEL_ID
        return _model_is_setup(model_id)

    def _update_download_notification(
        self,
        *,
        model_id: str,
        progress: float,
    ) -> None:
        extra_information = ReadableInformation(
            text="""\
The download progress is shown in the radial progress bar at the top left corner of \
the screen.""",
        )
        entry = model_for(model_id)
        label = entry.id if entry is not None else model_id
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=VOSK_DOWNLOAD_NOTIFICATION_ID,
                    title='Downloading',
                    content=f'Vosk model: {label}',
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

    def _handle_error(self, model_id: str) -> None:
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
        shutil.rmtree(_model_dir(model_id), ignore_errors=True)

    def download_model(
        self,
        model_id: str | None = None,
        *,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Download Vosk *model_id* archive and extract it under ``DATA_PATH``.

        Mirrors ``PiperEngine.download_voice``: ``on_complete`` is invoked
        once after the task settles — used by the initial setup flow to
        unblock ``_setup``'s ``await event.wait()``.
        """
        target_model = model_id or _read_selected_model()
        model_dir = _model_dir(target_model)
        zip_path = _download_zip(target_model)

        shutil.rmtree(model_dir, ignore_errors=True)
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            logger.exception(
                'Failed to remove stale Vosk archive',
                extra={'model_id': target_model, 'path': str(zip_path)},
            )

        self._update_download_notification(model_id=target_model, progress=0)

        async def download() -> None:
            try:
                zip_path.parent.mkdir(parents=True, exist_ok=True)
                model_dir.parent.mkdir(parents=True, exist_ok=True)

                async for downloaded_bytes, size in download_file(
                    url=download_url_for(target_model),
                    path=zip_path,
                ):
                    if size:
                        self._update_download_notification(
                            model_id=target_model,
                            progress=min(1.0, downloaded_bytes / size),
                        )

                self._update_download_notification(
                    model_id=target_model,
                    progress=1.0,
                )

                process = await asyncio.create_subprocess_exec(
                    '/usr/bin/env',
                    'unzip',
                    '-o',
                    str(zip_path),
                    '-d',
                    str(model_dir.parent),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await process.wait()

                await self.refresh_downloaded_models()
                store.dispatch(
                    SpeechRecognitionSetSlotEnabledAction(
                        mode=WakeMode.INTENTS,
                        enabled=True,
                    ),
                    AssistantUpdateProvidersAction(),
                )
                decide = getattr(self, 'decide_running_state', None)
                if decide is not None:
                    decide()
            except Exception:
                self._handle_error(target_model)
                raise
            finally:
                try:
                    zip_path.unlink(missing_ok=True)
                except OSError:
                    logger.exception(
                        'Failed to remove Vosk archive after extraction',
                        extra={'model_id': target_model, 'path': str(zip_path)},
                    )
                if on_complete is not None:
                    on_complete()

        create_task(download())

    @override
    async def _setup(self) -> None:
        if self.is_setup:
            return

        target_model = _read_selected_model()
        event = asyncio.Event()

        def _trigger_download() -> None:
            self.download_model(target_model, on_complete=event.set)

        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Vosk Engine Setup',
                    content=f'Download model: {target_model}',
                    color=WARNING_COLOR,
                    actions=[
                        create_notification_action(
                            label='Download Model',
                            icon='󰇚',
                            action=_trigger_download,
                        ),
                    ],
                ),
            ),
        )
        await event.wait()

    async def refresh_downloaded_models(self) -> None:
        """Scan the catalog for already-downloaded models and cache the set."""
        downloaded = tuple(
            model.id
            for language in VOSK_LANGUAGES
            for model in language.models
            if _model_is_setup(model.id)
        )
        store.dispatch(
            AssistantSetVoskDownloadedModelsAction(models=downloaded),
        )

    async def delete_model(self, model_id: str) -> None:
        """Delete a downloaded Vosk model directory and refresh the cache."""
        model_dir = _model_dir(model_id)
        try:
            shutil.rmtree(model_dir, ignore_errors=True)
            _download_zip(model_id).unlink(missing_ok=True)
        except OSError:
            logger.exception(
                'Failed to delete Vosk model',
                extra={'model_id': model_id, 'path': str(model_dir)},
            )
        await self.refresh_downloaded_models()
        store.dispatch(AssistantUpdateProvidersAction())

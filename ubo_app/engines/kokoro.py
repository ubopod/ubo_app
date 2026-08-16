"""Kokoro engine interface."""

from __future__ import annotations

import asyncio
from functools import reduce
from typing import TYPE_CHECKING

from typing_extensions import override

from ubo_app.colors import DANGER_COLOR, INFO_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.constants.assistant import (
    KOKORO_DOWNLOAD_NOTIFICATION_ID,
    KOKORO_DOWNLOAD_PROGRESS_NOTIFICATION_ID,
)
from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.kokoro_catalog import (
    DEFAULT_KOKORO_VOICE_ID,
    KOKORO_DIR,
    model_path,
    model_url,
    voice_for,
    voices_bin_path,
    voices_bin_url,
)
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantSetKokoroDownloadedAction,
    AssistantUpdateProvidersAction,
)
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.download import download_file
from ubo_app.utils.zip_latest import zip_latest

if TYPE_CHECKING:
    from collections.abc import Callable


def _kokoro_is_setup() -> bool:
    """Return True iff both the ONNX model and voices bin exist on disk."""
    return model_path().exists() and voices_bin_path().exists()


@store.with_state(lambda state: state.assistant.selected_kokoro_voice)
def _read_selected_voice(selected_voice: str) -> str:
    """Read the user's currently selected Kokoro voice id from the store."""
    return selected_voice or DEFAULT_KOKORO_VOICE_ID


class KokoroEngine(NeedsSetupMixin, AIProviderMixin):
    """Kokoro engine — offline TTS with all voices in one bundled file."""

    @property
    def name(self) -> str:
        """The internal name of the Kokoro engine."""
        return 'kokoro'

    @property
    def label(self) -> str:
        """The display label for the Kokoro engine."""
        return 'Kokoro'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the Kokoro bundle has not been downloaded."""
        return (
            'Kokoro models not downloaded. Pick a voice in Settings to '
            'download the bundle.'
        )

    @property
    @override
    def is_setup(self) -> bool:
        """Return True iff the bundled Kokoro files exist on disk."""
        return _kokoro_is_setup()

    def _show_download_started_notification(self, voice_id: str) -> None:
        """Dispatch the STICKY 'download started' notification.

        Mirrors Piper's two-notification pattern — the sticky owns the
        screen and is user-dismissable; the BACKGROUND wheel (separate
        id) keeps advancing in the status bar even after the user
        navigates away.
        """
        entry = voice_for(voice_id)
        speaker = entry.speaker if entry is not None else voice_id
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=KOKORO_DOWNLOAD_NOTIFICATION_ID,
                    title='Downloading',
                    content=f'Kokoro models (voice: {speaker})',
                    display_type=NotificationDisplayType.STICKY,
                    color=INFO_COLOR,
                    icon='󰇚',
                    blink=False,
                    show_dismiss_action=True,
                    dismiss_on_close=True,
                ),
            ),
        )

    def _update_progress_notification(
        self,
        *,
        voice_id: str,
        progress: float,
    ) -> None:
        """Update the BACKGROUND download-progress notification."""
        entry = voice_for(voice_id)
        speaker = entry.speaker if entry is not None else voice_id
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=KOKORO_DOWNLOAD_PROGRESS_NOTIFICATION_ID,
                    title='Downloading',
                    content=f'Kokoro models (voice: {speaker})',
                    display_type=NotificationDisplayType.BACKGROUND,
                    color=INFO_COLOR,
                    icon='󰇚',
                    blink=False,
                    progress=progress,
                    show_dismiss_action=False,
                    dismiss_on_close=False,
                ),
            ),
        )

    def _show_download_complete_notification(self, voice_id: str) -> None:
        """Dispatch the terminal FLASH 'download complete' notification."""
        entry = voice_for(voice_id)
        speaker = entry.speaker if entry is not None else voice_id
        store.dispatch(
            NotificationsClearByIdAction(id=KOKORO_DOWNLOAD_PROGRESS_NOTIFICATION_ID),
            NotificationsAddAction(
                notification=Notification(
                    id=KOKORO_DOWNLOAD_NOTIFICATION_ID,
                    title='Download Complete',
                    content=f'Kokoro ready — "{speaker}" selected',
                    display_type=NotificationDisplayType.FLASH,
                    flash_time=6,
                    color=SUCCESS_COLOR,
                    icon='󰄬',
                    blink=False,
                    show_dismiss_action=True,
                    dismiss_on_close=True,
                ),
            ),
        )

    def _handle_error(self) -> None:
        store.dispatch(
            NotificationsClearByIdAction(id=KOKORO_DOWNLOAD_PROGRESS_NOTIFICATION_ID),
            NotificationsAddAction(
                notification=Notification(
                    id=KOKORO_DOWNLOAD_NOTIFICATION_ID,
                    title='Kokoro',
                    content='Failed to download models',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                    show_dismiss_action=True,
                    dismiss_on_close=True,
                ),
            ),
        )
        # Clean up partial files so the next attempt starts fresh.
        for path in (model_path(), voices_bin_path()):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    'Failed to clean up partial Kokoro file',
                    extra={'path': str(path)},
                )

    def download_voice(
        self,
        voice_id: str | None = None,
        *,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Download the bundled Kokoro model + voices files (one-shot).

        Reentered any time the user picks a voice before the bundle is
        present. ``voice_id`` is carried only so the notification can
        name the voice the user selected — the actual download is the
        same for every voice. ``on_complete`` fires once after the task
        settles (success or failure).
        """
        target_voice = voice_id or _read_selected_voice()
        onnx = model_path()
        voices = voices_bin_path()

        if _kokoro_is_setup():
            # Already on disk — nothing to do beyond signalling the caller.
            if on_complete is not None:
                on_complete()
            return

        # Clear any partial files left from an interrupted previous run.
        for path in (onnx, voices):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    'Failed to remove stale Kokoro file',
                    extra={'path': str(path)},
                )

        self._show_download_started_notification(target_voice)
        self._update_progress_notification(voice_id=target_voice, progress=0)

        async def download() -> None:
            try:
                KOKORO_DIR.mkdir(parents=True, exist_ok=True)

                async for download_report in zip_latest(
                    download_file(url=model_url(), path=onnx),
                    download_file(url=voices_bin_url(), path=voices),
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
                        self._update_progress_notification(
                            voice_id=target_voice,
                            progress=min(1.0, downloaded_bytes / size),
                        )

                self._show_download_complete_notification(target_voice)
                await self.refresh_downloaded_state()
                # Refresh provider setup status so the Manage menu
                # picks up the new ``is_setup=True`` reading. The
                # subprocess doesn't need a nudge: it lazily
                # instantiates ``KokoroTTSService`` the next time the
                # TTS selector routes to ``kokoro`` and the files now
                # exist.
                store.dispatch(AssistantUpdateProvidersAction())
            except Exception:
                self._handle_error()
                raise
            finally:
                if on_complete is not None:
                    on_complete()

        create_task(download())

    @override
    async def _setup(self) -> None:
        if self.is_setup:
            return

        target_voice = _read_selected_voice()
        entry = voice_for(target_voice)
        speaker = entry.speaker if entry is not None else target_voice

        event = asyncio.Event()

        def _trigger_download() -> None:
            self.download_voice(target_voice, on_complete=event.set)

        from ubo_app.store.services.notification_helpers import (
            create_notification_action,
        )

        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Kokoro Engine Setup',
                    content=f'Download models for voice: {speaker}',
                    color=WARNING_COLOR,
                    actions=[
                        create_notification_action(
                            label='Download Models',
                            icon='󰇚',
                            action=_trigger_download,
                        ),
                    ],
                ),
            ),
        )
        await event.wait()

    async def refresh_downloaded_state(self) -> None:
        """Cache whether the bundled Kokoro files are on disk."""
        store.dispatch(
            AssistantSetKokoroDownloadedAction(downloaded=_kokoro_is_setup()),
        )

    async def delete_bundle(self) -> None:
        """Delete the Kokoro model + voices bundle and refresh the cache."""
        for path in (model_path(), voices_bin_path()):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    'Failed to delete Kokoro file',
                    extra={'path': str(path)},
                )
        await self.refresh_downloaded_state()
        store.dispatch(AssistantUpdateProvidersAction())

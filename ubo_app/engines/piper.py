"""Piper engine interface."""

from __future__ import annotations

import asyncio
import hashlib
import json
from functools import reduce
from pathlib import Path
from typing import TYPE_CHECKING

import aiostream
from typing_extensions import override

from ubo_app.colors import DANGER_COLOR, INFO_COLOR, SUCCESS_COLOR, WARNING_COLOR
from ubo_app.constants.assistant import (
    PIPER_DOWNLOAD_NOTIFICATION_ID,
    PIPER_DOWNLOAD_PROGRESS_NOTIFICATION_ID,
)
from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.piper_catalog import (
    DEFAULT_PIPER_VOICE_ID,
    PIPER_LANGUAGES,
    json_path_for,
    json_url_for,
    model_path_for,
    model_url_for,
    voice_for,
)
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantSetPiperDownloadedVoicesAction,
    AssistantUpdateProvidersAction,
)
from ubo_app.store.services.notification_helpers import create_notification_action
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearByIdAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.download import download_file

if TYPE_CHECKING:
    from collections.abc import Callable


def _onnx_path(voice_id: str) -> Path:
    return Path(str(model_path_for(voice_id)))


def _json_path(voice_id: str) -> Path:
    return Path(str(json_path_for(voice_id)))


def _voice_is_setup(voice_id: str) -> bool:
    """Return True iff *voice_id* has both files on disk (hash matches if known)."""
    onnx = _onnx_path(voice_id)
    metadata = _json_path(voice_id)
    if not onnx.exists() or not metadata.exists():
        return False

    try:
        with metadata.open('r') as f:
            json.load(f)
    except (OSError, json.JSONDecodeError):
        return False

    entry = voice_for(voice_id)
    expected_hash = entry.onnx_sha256 if entry is not None else ''
    if not expected_hash:
        return True

    sha256_hash = hashlib.sha256()
    try:
        with onnx.open('rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256_hash.update(chunk)
    except OSError:
        return False
    return sha256_hash.hexdigest() == expected_hash


@store.with_state(lambda state: state.assistant.selected_piper_voice)
def _read_selected_voice(selected_voice: str) -> str:
    """Read the user's currently selected voice id from the store."""
    return selected_voice or DEFAULT_PIPER_VOICE_ID


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
        """Message shown when the Piper voice model is missing."""
        return (
            'Piper voice model not found. Pick a voice in Settings to download '
            'it.'
        )

    @property
    @override
    @store.with_state(lambda state: state.assistant.selected_piper_voice)
    def is_setup(  # noqa: PLR0206
        self,
        selected_voice: str,
    ) -> bool:
        """Return True iff the currently selected voice exists on disk."""
        voice_id = selected_voice or DEFAULT_PIPER_VOICE_ID
        return _voice_is_setup(voice_id)

    def _show_download_started_notification(self, voice_id: str) -> None:
        """Dispatch the STICKY 'download started' notification.

        Uses ``PIPER_DOWNLOAD_NOTIFICATION_ID`` — the same id the terminal
        FLASH uses, so on completion the FLASH overwrites this in place.
        It owns the screen and is user-dismissable; dismissing it (or
        navigating away) does not stop the download — the BACKGROUND
        progress notification has its own id and keeps the status-bar
        wheel advancing. Carries no ``progress`` itself, so it never adds
        a redundant wheel of its own.
        """
        entry = voice_for(voice_id)
        speaker = entry.speaker if entry is not None else voice_id
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=PIPER_DOWNLOAD_NOTIFICATION_ID,
                    title='Downloading',
                    content=f'Piper voice: {speaker}',
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
        """Update the BACKGROUND download-progress notification.

        Uses ``PIPER_DOWNLOAD_PROGRESS_NOTIFICATION_ID`` — its own id,
        independent of the on-screen STICKY/FLASH notification. BACKGROUND
        so it is filtered out of the on-screen view and shows only as the
        radial progress wheel in the status bar; it survives the user
        dismissing the sticky / navigating away and keeps advancing until
        the download finishes.
        """
        entry = voice_for(voice_id)
        speaker = entry.speaker if entry is not None else voice_id
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=PIPER_DOWNLOAD_PROGRESS_NOTIFICATION_ID,
                    title='Downloading',
                    content=f'Piper voice: {speaker}',
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
        """Dispatch the terminal FLASH 'download complete' notification.

        Reuses ``PIPER_DOWNLOAD_NOTIFICATION_ID`` so it overwrites the
        STICKY in place if it is still on screen, or simply appears if the
        user already dismissed it. FLASH so it takes over the screen and
        auto-dismisses after ``flash_time``; it is also user-dismissable.
        Clears the BACKGROUND progress notification — the download is done,
        so the status-bar wheel goes away.
        """
        entry = voice_for(voice_id)
        speaker = entry.speaker if entry is not None else voice_id
        store.dispatch(
            NotificationsClearByIdAction(id=PIPER_DOWNLOAD_PROGRESS_NOTIFICATION_ID),
            NotificationsAddAction(
                notification=Notification(
                    id=PIPER_DOWNLOAD_NOTIFICATION_ID,
                    title='Download Complete',
                    content=f'"{speaker}" voice downloaded',
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

    def _handle_error(self, voice_id: str) -> None:
        store.dispatch(
            NotificationsClearByIdAction(id=PIPER_DOWNLOAD_PROGRESS_NOTIFICATION_ID),
            NotificationsAddAction(
                notification=Notification(
                    id=PIPER_DOWNLOAD_NOTIFICATION_ID,
                    title='Piper',
                    content='Failed to download voice',
                    display_type=NotificationDisplayType.STICKY,
                    color=DANGER_COLOR,
                    icon='󰜺',
                    chime=Chime.FAILURE,
                    show_dismiss_action=True,
                    dismiss_on_close=True,
                ),
            ),
        )
        onnx = _onnx_path(voice_id)
        try:
            onnx.unlink(missing_ok=True)
        except OSError:
            logger.exception(
                'Failed to clean up partial Piper download',
                extra={'voice_id': voice_id, 'path': str(onnx)},
            )

    def download_voice(
        self,
        voice_id: str | None = None,
        *,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Download Piper voice files for *voice_id* (default = current).

        Re-entered any time the user picks a not-yet-downloaded voice
        from the Piper sub-menu. ``on_complete`` is invoked once after
        the task settles — used by the initial setup flow to unblock
        ``_setup``'s ``await event.wait()``.
        """
        target_voice = voice_id or _read_selected_voice()
        onnx = _onnx_path(target_voice)
        metadata = _json_path(target_voice)

        for path in (onnx, metadata):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    'Failed to remove stale Piper file',
                    extra={'voice_id': target_voice, 'path': str(path)},
                )

        # Sticky first (owns the screen, dismissable), then the BACKGROUND
        # progress wheel appears in the status bar.
        self._show_download_started_notification(target_voice)
        self._update_progress_notification(voice_id=target_voice, progress=0)

        async def download() -> None:
            try:
                onnx.parent.mkdir(parents=True, exist_ok=True)

                async for download_report in aiostream.stream.ziplatest(
                    download_file(
                        url=model_url_for(target_voice),
                        path=onnx,
                    ),
                    download_file(
                        url=json_url_for(target_voice),
                        path=metadata,
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
                        self._update_progress_notification(
                            voice_id=target_voice,
                            progress=min(1.0, downloaded_bytes / size),
                        )

                self._show_download_complete_notification(target_voice)
                await self.refresh_downloaded_voices()
                # Refresh provider setup status so `is_setup` re-evaluates
                # against the freshly-downloaded file. The subprocess does
                # not need a nudge here: it already recorded the requested
                # voice when the user picked it, and `PiperTTSService.run_tts`
                # self-heals — it loads the requested voice before the next
                # utterance now that the .onnx file exists on disk.
                store.dispatch(AssistantUpdateProvidersAction())
            except Exception:
                self._handle_error(target_voice)
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

        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Piper Engine Setup',
                    content=f'Download voice: {speaker}',
                    color=WARNING_COLOR,
                    actions=[
                        create_notification_action(
                            label='Download Voice',
                            icon='󰇚',
                            action=_trigger_download,
                        ),
                    ],
                ),
            ),
        )
        await event.wait()

    async def refresh_downloaded_voices(self) -> None:
        """Scan the catalog for already-downloaded voices and cache the set."""
        downloaded = tuple(
            voice.id
            for language in PIPER_LANGUAGES
            for voice in language.voices
            if _voice_is_setup(voice.id)
        )
        store.dispatch(
            AssistantSetPiperDownloadedVoicesAction(voices=downloaded),
        )

    async def delete_voice(self, voice_id: str) -> None:
        """Delete a downloaded Piper voice's files and refresh the cache."""
        for path in (_onnx_path(voice_id), _json_path(voice_id)):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    'Failed to delete Piper voice file',
                    extra={'voice_id': voice_id, 'path': str(path)},
                )
        await self.refresh_downloaded_voices()
        store.dispatch(AssistantUpdateProvidersAction())

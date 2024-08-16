# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, ParamSpec

from audio_manager import AudioManager
from constants import AUDIO_MIC_STATE_ICON_ID, AUDIO_MIC_STATE_ICON_PRIORITY

from ubo_app.store.main import autorun, dispatch, subscribe_event
from ubo_app.store.services.audio import AudioPlayAudioEvent, AudioPlayChimeEvent
from ubo_app.store.status_icons import StatusIconsRegisterAction
from ubo_app.utils.async_ import to_thread
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

Args = ParamSpec('Args')


def _run_async_in_thread(
    async_func: Callable[Args, Coroutine],
    *args: Args.args,
    **kwargs: Args.kwargs,
) -> None:
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(async_func(*args, **kwargs))
    loop.close()
    return result


def init_service() -> None:
    audio_manager = AudioManager()

    dispatch(
        StatusIconsRegisterAction(
            icon='󰍭',
            priority=AUDIO_MIC_STATE_ICON_PRIORITY,
            id=AUDIO_MIC_STATE_ICON_ID,
        ),
    )

    @autorun(lambda state: state.audio.playback_volume)
    def _(volume: float) -> None:
        audio_manager.set_playback_volume(volume)

    @autorun(lambda state: state.audio.capture_volume)
    def _(volume: float) -> None:
        audio_manager.set_capture_volume(volume)

    @autorun(lambda state: state.audio.is_playback_mute)
    def _(is_mute: bool) -> None:  # noqa: FBT001
        audio_manager.set_playback_mute(mute=is_mute)

    subscribe_event(
        AudioPlayChimeEvent,
        lambda event: audio_manager.play_file(
            Path(__file__).parent.joinpath(f'sounds/{event.name}.wav').as_posix(),
        ),
    )

    subscribe_event(
        AudioPlayAudioEvent,
        lambda event: to_thread(
            _run_async_in_thread,
            audio_manager.play_sequence,
            event.sample,
            id=event.id,
            channels=event.channels,
            rate=event.rate,
            width=event.width,
        ),
    )

    register_persistent_store(
        'audio_state:playback_volume',
        lambda state: state.audio.playback_volume,
    )
    register_persistent_store(
        'audio_state:is_playback_mute',
        lambda state: state.audio.is_playback_mute,
    )
    register_persistent_store(
        'audio_state:capture_volume',
        lambda state: state.audio.capture_volume,
    )
    register_persistent_store(
        'audio_state:is_capture_mute',
        lambda state: state.audio.is_capture_mute,
    )

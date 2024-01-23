# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from pathlib import Path

from audio_manager import AudioManager
from constants import SOUND_MIC_STATE_ICON_ID, SOUND_MIC_STATE_ICON_PRIORITY

from ubo_app.store import autorun, dispatch, subscribe_event
from ubo_app.store.services.sound import SoundPlayChimeEvent
from ubo_app.store.status_icons import StatusIconsRegisterAction


def init_service() -> None:
    dispatch(
        StatusIconsRegisterAction(
            icon='mic_off',
            priority=SOUND_MIC_STATE_ICON_PRIORITY,
            id=SOUND_MIC_STATE_ICON_ID,
        ),
    )

    audio_manager = AudioManager()

    @autorun(lambda state: state.sound.playback_volume)
    def sync_playback_volume(volume: float) -> None:
        audio_manager.set_playback_volume(volume)

    @autorun(lambda state: state.sound.capture_volume)
    def sync_capture_volume(volume: float) -> None:
        audio_manager.set_capture_volume(volume)

    @autorun(lambda state: state.sound.is_playback_mute)
    def sync_playback_mute(is_mute: bool) -> None:  # noqa: FBT001
        audio_manager.set_playback_mute(mute=is_mute)

    subscribe_event(
        SoundPlayChimeEvent,
        lambda event: audio_manager.play(
            Path(__file__).parent.joinpath(f'sounds/{event.name}.wav').as_posix(),
        ),
    )

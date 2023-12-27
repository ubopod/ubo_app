# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from constants import SOUND_MIC_STATE_ICON_ID, SOUND_MIC_STATE_ICON_PRIORITY

from ubo_app.store import dispatch
from ubo_app.store.status_icons import StatusIconsRegisterAction


def init_service() -> None:
    dispatch(
        StatusIconsRegisterAction(
            icon='mic_off',
            priority=SOUND_MIC_STATE_ICON_PRIORITY,
            id=SOUND_MIC_STATE_ICON_ID,
        ),
    )

# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from ubo_app.store import dispatch
from ubo_app.store.status_icons import (
    StatusIconsRegisterAction,
    StatusIconsRegisterActionPayload,
)


def init_service() -> None:
    dispatch(
        StatusIconsRegisterAction(
            payload=StatusIconsRegisterActionPayload(
                icon='mic_off',
                priority=-2,
                id='sound_mic_status',
            ),
        ),
    )


if __name__ == '__ubo_service__':
    init_service()

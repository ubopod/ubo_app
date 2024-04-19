"""Implement `init_service` for vocie module."""

from __future__ import annotations

import pvorca
from redux import FinishEvent
from ubo_gui.menu.types import ActionItem, HeadedMenu, SubMenuItem

from ubo_app.constants import PICOVOICE_API_KEY
from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.main import RegisterSettingAppAction
from ubo_app.store.services.sound import SoundPlayAudioAction
from ubo_app.store.services.voice import VoiceSynthesizeTextEvent
from ubo_app.utils.async_ import create_task
from ubo_app.utils.qrcode import qrcode_input


def init_service() -> None:
    """Initialize vocie service."""
    orca: pvorca.Orca | None = None

    if PICOVOICE_API_KEY:
        orca = pvorca.create(access_key=PICOVOICE_API_KEY)

    def input_access_token() -> None:
        async def act() -> None:
            nonlocal orca
            orca = pvorca.create(
                access_key=(
                    await qrcode_input(
                        '.*',
                        prompt='Enter the Picovoice API key',
                    )
                )[0],
            )

        create_task(act())

    def synthesize(event: VoiceSynthesizeTextEvent) -> None:
        if not orca:
            return
        audio_sequence = orca.synthesize(
            text=event.text,
            speech_rate=event.speech_rate,
        )

        dispatch(
            SoundPlayAudioAction(
                sample=audio_sequence,
                channels=1,
                rate=orca.sample_rate,
                width=2,
            ),
        )

    subscribe_event(VoiceSynthesizeTextEvent, synthesize)

    dispatch(
        RegisterSettingAppAction(
            menu_item=SubMenuItem(
                label='Voice',
                sub_menu=HeadedMenu(
                    title='Voice Settings',
                    heading='󰔊',
                    sub_heading='Set the access token for picovoice service',
                    items=[
                        ActionItem(
                            label='Access Token',
                            icon='󰐲',
                            action=input_access_token,
                        ),
                    ],
                ),
            ),
        ),
    )

    def cleanup() -> None:
        if orca:
            orca.delete()

    subscribe_event(FinishEvent, cleanup)

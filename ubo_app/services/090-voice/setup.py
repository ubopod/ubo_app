"""Implement `init_service` for vocie module."""

from __future__ import annotations

from asyncio import CancelledError

import pvorca
from redux import FinishEvent
from ubo_gui.menu.types import ActionItem, HeadedMenu, SubMenuItem

from ubo_app.constants import PICOVOICE_ACCESS_KEY
from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.main import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.services.sound import SoundPlayAudioAction
from ubo_app.store.services.voice import VoiceSynthesizeTextEvent
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task, to_thread
from ubo_app.utils.qrcode import qrcode_input


class _Context:
    orca_instance: pvorca.Orca | None = None

    def cleanup(self: _Context) -> None:
        if self.orca_instance:
            self.orca_instance.delete()
            self.orca_instance = None

    def set_access_key(self: _Context, access_key: str | None) -> None:
        self.cleanup()
        if access_key:
            self.orca_instance = pvorca.create(access_key)


_context = _Context()


def input_access_key() -> None:
    """Input the Picovoice access key."""

    async def act() -> None:
        try:
            access_key = (
                await qrcode_input(
                    '.*',
                    prompt='Convert the Picovoice access key to a QR code and '
                    'scan it.',
                )
            )[0]
            secrets.write_secret(key=PICOVOICE_ACCESS_KEY, value=access_key)
            _context.set_access_key(access_key)
        except CancelledError:
            pass

    create_task(act())


def clear_access_key() -> None:
    """Clear the Picovoice access key."""
    _context.cleanup()
    secrets.clear_secret(PICOVOICE_ACCESS_KEY)


def synthesize(event: VoiceSynthesizeTextEvent) -> None:
    """Synthesize the text."""
    if not _context.orca_instance:
        return
    rate = _context.orca_instance.sample_rate
    audio_sequence = _context.orca_instance.synthesize(
        text=event.text,
        speech_rate=event.speech_rate,
    )

    dispatch(
        SoundPlayAudioAction(sample=audio_sequence, channels=1, rate=rate, width=2),
    )


def init_service() -> None:
    """Initialize voice service."""
    access_key = secrets.read_secret(PICOVOICE_ACCESS_KEY)
    to_thread(_context.set_access_key, access_key)

    subscribe_event(VoiceSynthesizeTextEvent, synthesize)

    dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.INTERFACE,
            priority=0,
            menu_item=SubMenuItem(
                label='Voice',
                icon='󰔊',
                sub_menu=HeadedMenu(
                    title='Voice Settings',
                    heading='󰔊 Picovoice',
                    sub_heading='Set the access key\n Current value: '
                    f'{secrets.read_covered_secret(PICOVOICE_ACCESS_KEY)}',
                    items=[
                        ActionItem(
                            label='Set Access Key',
                            icon='󰐲',
                            action=input_access_key,
                        ),
                        ActionItem(
                            label='Clear Access Key',
                            icon='󰌊',
                            action=clear_access_key,
                        ),
                    ],
                ),
            ),
        ),
    )

    subscribe_event(FinishEvent, _context.cleanup)

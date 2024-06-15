"""Implement `init_service` for vocie module."""

from __future__ import annotations

import re
from asyncio import CancelledError
from threading import Lock
from typing import TYPE_CHECKING

import pvorca
from redux import FinishEvent
from ubo_gui.menu.types import ActionItem, HeadedMenu, SubMenuItem

from ubo_app.constants import PICOVOICE_ACCESS_KEY
from ubo_app.store.core import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import autorun, dispatch, subscribe_event
from ubo_app.store.services.sound import SoundPlayAudioAction
from ubo_app.store.services.voice import (
    VoiceSynthesizeTextEvent,
    VoiceUpdateAccessKeyStatus,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task, to_thread
from ubo_app.utils.qrcode import qrcode_input

if TYPE_CHECKING:
    from collections.abc import Sequence


class _Context:
    orca_instance: pvorca.Orca | None = None
    lock: Lock = Lock()

    def cleanup(self: _Context) -> None:
        dispatch(VoiceUpdateAccessKeyStatus(is_access_key_set=False))
        with self.lock:
            if self.orca_instance:
                self.orca_instance.delete()
                self.orca_instance = None

    def set_access_key(self: _Context, access_key: str) -> None:
        dispatch(VoiceUpdateAccessKeyStatus(is_access_key_set=True))
        with self.lock:
            if access_key:
                if self.orca_instance:
                    self.orca_instance.delete()
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
            to_thread(_context.set_access_key, access_key)
        except CancelledError:
            pass

    create_task(act())


def clear_access_key() -> None:
    """Clear the Picovoice access key."""
    secrets.clear_secret(PICOVOICE_ACCESS_KEY)
    to_thread(_context.cleanup)


def synthesize(event: VoiceSynthesizeTextEvent) -> None:
    """Synthesize the text."""
    with _context.lock:
        if not _context.orca_instance:
            return
        rate = _context.orca_instance.sample_rate

        valid_characters = re.sub(
            r'[\^\$\-\\]',
            lambda match: f'\\{match.group()}',
            ''.join(
                sorted(
                    {
                        i
                        for i in _context.orca_instance.valid_characters
                        if i not in '{|}'
                    },
                ),
            ),
        )

        def remove_disallowed_characters(text: str) -> str:
            return re.sub(rf'[^{valid_characters}]', '', text)

        components = re.split(r'(\{[^{|}]*\|[^{|}]*\})', event.text)
        processed_components = [
            remove_disallowed_characters(component) if index % 2 == 0 else component
            for index, component in enumerate(components)
        ]
        processed_text = ''.join(processed_components)
        audio_sequence = _context.orca_instance.synthesize(
            text=processed_text,
            speech_rate=event.speech_rate,
        )

        dispatch(
            SoundPlayAudioAction(
                sample=audio_sequence[0],
                channels=1,
                rate=rate,
                width=2,
            ),
        )


@autorun(lambda state: state.voice.is_access_key_set)
def _menu_items(is_access_key_set: bool | None) -> Sequence[ActionItem]:
    if is_access_key_set:
        return [
            ActionItem(
                label='Clear Access Key',
                icon='󰌊',
                action=clear_access_key,
            ),
        ]
    return [
        ActionItem(
            label='Set Access Key',
            icon='󰐲',
            action=input_access_key,
        ),
    ]


@autorun(lambda state: state.voice.is_access_key_set)
def _menu_sub_heading(_: bool | None) -> str:
    return f"""Set the access key
Current value: {secrets.read_covered_secret(PICOVOICE_ACCESS_KEY)}"""


def init_service() -> None:
    """Initialize voice service."""
    access_key = secrets.read_secret(PICOVOICE_ACCESS_KEY)
    if access_key:
        to_thread(_context.set_access_key, access_key)
    else:
        to_thread(_context.cleanup)

    subscribe_event(VoiceSynthesizeTextEvent, synthesize)

    dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ACCESSIBILITY,
            priority=0,
            menu_item=SubMenuItem(
                label='Voice',
                icon='󰔊',
                sub_menu=HeadedMenu(
                    title='Voice Settings',
                    heading='󰔊 Picovoice',
                    sub_heading=_menu_sub_heading,
                    items=_menu_items,
                ),
            ),
        ),
    )

    subscribe_event(FinishEvent, _context.cleanup)

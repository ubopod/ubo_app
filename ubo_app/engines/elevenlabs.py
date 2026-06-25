"""ElevenLabs engine interface."""

from __future__ import annotations

import re

import aiohttp
from typing_extensions import override

from ubo_app.constants.assistant import (
    ELEVENLABS_API_KEY_PATTERN,
    ELEVENLABS_API_KEY_SECRET_ID,
    ELEVENLABS_VOICE_ID,
    ELEVENLABS_VOICE_ID_PATTERN,
)
from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
from ubo_app.logger import logger
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    QRCodeInputDescription,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantAddElevenLabsVoiceAction,
    AssistantSetElevenLabsAvailableVoicesAction,
    ElevenLabsVoiceEntry,
)
from ubo_app.store.services.notifications import (
    Chime,
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils import secrets
from ubo_app.utils.input import ubo_input

# ``GET /v2/voices`` returns the account's default/premade voices plus the
# user's own cloned voices.
ELEVENLABS_VOICES_URL = 'https://api.elevenlabs.io/v2/voices'
ELEVENLABS_VOICES_TIMEOUT_SECONDS = 10
ELEVENLABS_VOICES_MAX_PAGES = 20
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403


def _parse_voices_page(payload: object) -> list[ElevenLabsVoiceEntry]:
    """Extract ``ElevenLabsVoiceEntry`` items from one ``/v2/voices`` page."""
    if not isinstance(payload, dict):
        return []
    entries: list[ElevenLabsVoiceEntry] = []
    for voice in payload.get('voices', []):
        if not isinstance(voice, dict):
            continue
        voice_id = voice.get('voice_id')
        name = voice.get('name')
        if isinstance(voice_id, str) and voice_id and isinstance(name, str):
            entries.append(ElevenLabsVoiceEntry(id=voice_id, label=name or voice_id))
    return entries


class ElevenLabsEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """ElevenLabs engine."""

    credential_secret_ids = (ELEVENLABS_API_KEY_SECRET_ID, ELEVENLABS_VOICE_ID)

    @property
    def name(self) -> str:
        """The internal name of the ElevenLabs engine."""
        return 'elevenlabs'

    @property
    def label(self) -> str:
        """The display label for the ElevenLabs engine."""
        return 'ElevenLabs'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the ElevenLabs service API key is not set."""
        return (
            'ElevenLabs service API key and voice ID are not set. '
            'You can set them in the settings.'
        )

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the ElevenLabs engine is set up."""
        api_key = secrets.read_secret(ELEVENLABS_API_KEY_SECRET_ID)
        voice_id = secrets.read_secret(ELEVENLABS_VOICE_ID)

        return (
            bool(api_key)
            and bool(voice_id)
            and re.match(ELEVENLABS_API_KEY_PATTERN, api_key) is not None
            and re.match(ELEVENLABS_VOICE_ID_PATTERN, voice_id) is not None
        )

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='ElevenLabs Configuration',
            prompt='Enter your ElevenLabs API key and voice ID.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='API Key',
                            description='Enter your ElevenLabs API key',
                            required=True,
                            pattern=ELEVENLABS_API_KEY_PATTERN,
                        ),
                        InputFieldDescription(
                            name='voice_id',
                            type=InputFieldType.TEXT,
                            label='Voice ID',
                            description='Enter your ElevenLabs voice ID',
                            required=True,
                            pattern=ELEVENLABS_VOICE_ID_PATTERN,
                        ),
                        InputFieldDescription(
                            name='name',
                            type=InputFieldType.TEXT,
                            label='Voice Name (optional)',
                            description='A human-readable name for this voice, '
                            'e.g. "Deep Voice Man"',
                            required=False,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='ElevenLabs Configuration',
                    instructions=ReadableInformation(
                        text='Convert your ElevenLabs API key and voice ID to a QR '
                        'code in the format "api_key:voice_id" and hold it in front '
                        'of the camera to scan it.',
                        picovoice_text='Convert your ElevenLabs API key and voice ID '
                        'to a {QR|K Y UW AA R} code in the format "API key colon '
                        'voice ID" and hold it in front of the camera to scan it.',
                    ),
                    pattern=(
                        r'(?P<api_key>' + ELEVENLABS_API_KEY_PATTERN + r'):'
                        r'(?P<voice_id>' + ELEVENLABS_VOICE_ID_PATTERN + r')'
                    ),
                ),
            ],
        )
        secrets.write_secret(
            key=ELEVENLABS_API_KEY_SECRET_ID,
            value=result.data['api_key'],
        )
        voice_id = result.data['voice_id']
        secrets.write_secret(
            key=ELEVENLABS_VOICE_ID,
            value=voice_id,
        )
        # Register the primary voice in the picker so it carries the optional
        # human-readable name (the named entry overrides the raw-id secret
        # fallback in the menu).
        name = (result.data.get('name') or '').strip()
        if name:
            store.dispatch(
                AssistantAddElevenLabsVoiceAction(voice_id=voice_id, name=name),
            )

    @override
    def _clear_credentials(self) -> None:
        """Forget the ElevenLabs API key and voice id."""
        secrets.clear_secret(ELEVENLABS_API_KEY_SECRET_ID)
        secrets.clear_secret(ELEVENLABS_VOICE_ID)

    async def fetch_voices(self) -> None:
        """Fetch the account's voices and cache them in the store.

        Queries ``GET /v2/voices`` (default/premade voices plus the user's own
        cloned voices) with the stored API key and dispatches
        ``AssistantSetElevenLabsAvailableVoicesAction``. Failure-safe: on any
        error the existing cache is left untouched so the picker keeps working
        offline and the manual "Add Voice ID" path still applies. Listing
        voices needs the ``voices_read`` key scope (separate from
        ``text_to_speech``), so a TTS-only key yields 401 — surfaced as a
        notification so the user can fix the scope or add ids manually.
        """
        api_key = (secrets.read_secret(ELEVENLABS_API_KEY_SECRET_ID) or '').strip()
        if not api_key:
            return
        try:
            entries = await self._request_voices(api_key)
        except aiohttp.ClientResponseError as error:
            logger.exception('Failed to fetch ElevenLabs voices')
            if error.status in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
                self._notify_fetch_failure(
                    'Your ElevenLabs API key cannot list voices. Enable the '
                    '"voices_read" permission on the key, or add voice IDs '
                    'manually.',
                )
            else:
                self._notify_fetch_failure(
                    'ElevenLabs rejected the voices request '
                    f'(HTTP {error.status}). You can add voice IDs manually.',
                )
            return
        except (aiohttp.ClientError, TimeoutError, ValueError):
            logger.exception('Failed to fetch ElevenLabs voices')
            self._notify_fetch_failure(
                'Could not reach ElevenLabs to list voices. Check your '
                'connection, or add voice IDs manually.',
            )
            return
        store.dispatch(
            AssistantSetElevenLabsAvailableVoicesAction(voices=tuple(entries)),
        )

    def _notify_fetch_failure(self, content: str) -> None:
        """Surface a voice-fetch failure so "Refresh" isn't silent."""
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    # Stable id: a repeated refresh replaces, never stacks.
                    id='assistant:elevenlabs-voices-fetch',
                    title='ElevenLabs Voices',
                    content=content,
                    importance=Importance.HIGH,
                    chime=Chime.FAILURE,
                    icon='󰀦',
                    display_type=NotificationDisplayType.FLASH,
                ),
            ),
        )

    async def _request_voices(self, api_key: str) -> list[ElevenLabsVoiceEntry]:
        """Page through ``/v2/voices`` and return the parsed voice entries."""
        headers = {'xi-api-key': api_key}
        timeout = aiohttp.ClientTimeout(total=ELEVENLABS_VOICES_TIMEOUT_SECONDS)
        entries: list[ElevenLabsVoiceEntry] = []
        next_page_token: str | None = None
        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
        ) as session:
            for _ in range(ELEVENLABS_VOICES_MAX_PAGES):
                params = {'page_size': '100'}
                if next_page_token:
                    params['next_page_token'] = next_page_token
                async with session.get(
                    ELEVENLABS_VOICES_URL,
                    params=params,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json()
                entries.extend(_parse_voices_page(payload))
                if not (isinstance(payload, dict) and payload.get('has_more')):
                    break
                next_page_token = payload.get('next_page_token')
                if not next_page_token:
                    break
        return entries

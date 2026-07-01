"""Mistral engine interface."""

import re

import aiohttp
from typing_extensions import override

from ubo_app.constants.assistant import (
    MISTRAL_API_KEY_PATTERN,
    MISTRAL_API_KEY_SECRET_ID,
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
    AssistantSetMistralAvailableVoicesAction,
    MistralVoiceEntry,
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

# ``GET /v1/audio/voices`` returns the preset voices plus the account's own
# cloned voices (``type=all``), paged with ``limit``/``offset``.
MISTRAL_VOICES_URL = 'https://api.mistral.ai/v1/audio/voices'
MISTRAL_VOICES_TIMEOUT_SECONDS = 10
MISTRAL_VOICES_PAGE_SIZE = 100
MISTRAL_VOICES_MAX_PAGES = 20
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403


def _parse_voices_page(payload: object) -> list[MistralVoiceEntry]:
    """Extract ``MistralVoiceEntry`` items from one ``/v1/audio/voices`` page.

    The voice id is the human-readable ``slug`` (e.g. ``casual_male``) when
    present, else the UUID ``id`` — pipecat's ``MistralTTSService`` accepts
    either.
    """
    if not isinstance(payload, dict):
        return []
    entries: list[MistralVoiceEntry] = []
    for voice in payload.get('items', []):
        if not isinstance(voice, dict):
            continue
        slug = voice.get('slug')
        uuid = voice.get('id')
        voice_id = slug if isinstance(slug, str) and slug else uuid
        if not (isinstance(voice_id, str) and voice_id):
            continue
        name = voice.get('name')
        label = name if isinstance(name, str) and name else voice_id
        entries.append(MistralVoiceEntry(id=voice_id, label=label))
    return entries


class MistralEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """Mistral engine."""

    credential_secret_ids = (MISTRAL_API_KEY_SECRET_ID,)

    CURATED_MODELS = (
        'mistral-small-latest',
        'mistral-medium-latest',
        'mistral-large-latest',
        'codestral-latest',
        'ministral-3b-latest',
        'ministral-8b-latest',
        'pixtral-large-latest',
    )

    @property
    def name(self) -> str:
        """The internal name of the Mistral engine."""
        return 'mistral'

    @property
    def label(self) -> str:
        """The display label for the Mistral engine."""
        return 'Mistral'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the Mistral service API key is not set."""
        return 'Mistral service API key is not set. You can set it in the settings.'

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the Mistral engine is set up."""
        api_key = secrets.read_secret(MISTRAL_API_KEY_SECRET_ID)
        return (
            bool(api_key)
            and re.match(MISTRAL_API_KEY_PATTERN, api_key) is not None
        )

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='Mistral API Key',
            prompt='Enter your Mistral API key.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='API Key',
                            description='Enter your Mistral API key',
                            required=True,
                            pattern=MISTRAL_API_KEY_PATTERN,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='Mistral API Key',
                    instructions=ReadableInformation(
                        text='Convert your Mistral API key to a QR code and hold it '
                        'in front of the camera to scan it.',
                        picovoice_text='Convert your {Mistral|M IH S T R AH L} API '
                        'key to a {QR|K Y UW AA R} code and hold it in front of the '
                        'camera to scan it.',
                    ),
                    pattern=r'(?P<api_key>' + MISTRAL_API_KEY_PATTERN + ')',
                ),
            ],
        )
        secrets.write_secret(
            key=MISTRAL_API_KEY_SECRET_ID,
            value=result.data['api_key'],
        )

    @override
    def _clear_credentials(self) -> None:
        """Forget the Mistral API key."""
        secrets.clear_secret(MISTRAL_API_KEY_SECRET_ID)

    async def fetch_voices(self) -> None:
        """Fetch the account's voices and cache them in the store.

        Queries ``GET /v1/audio/voices`` (presets plus the account's own cloned
        voices) with the stored API key and dispatches
        ``AssistantSetMistralAvailableVoicesAction``. Failure-safe: on any error
        the existing cache is left untouched so the picker keeps working
        offline (and the current selection / default still applies).
        """
        api_key = (secrets.read_secret(MISTRAL_API_KEY_SECRET_ID) or '').strip()
        if not api_key:
            return
        try:
            entries = await self._request_voices(api_key)
        except aiohttp.ClientResponseError as error:
            logger.exception('Failed to fetch Mistral voices')
            if error.status in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
                self._notify_fetch_failure(
                    'Your Mistral API key cannot list voices. Check the key '
                    'and its permissions.',
                )
            else:
                self._notify_fetch_failure(
                    'Mistral rejected the voices request '
                    f'(HTTP {error.status}).',
                )
            return
        except (aiohttp.ClientError, TimeoutError, ValueError):
            logger.exception('Failed to fetch Mistral voices')
            self._notify_fetch_failure(
                'Could not reach Mistral to list voices. Check your connection.',
            )
            return
        store.dispatch(
            AssistantSetMistralAvailableVoicesAction(voices=tuple(entries)),
        )

    def _notify_fetch_failure(self, content: str) -> None:
        """Surface a voice-fetch failure so "Refresh" isn't silent."""
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    # Stable id: a repeated refresh replaces, never stacks.
                    id='assistant:mistral-voices-fetch',
                    title='Mistral Voices',
                    content=content,
                    importance=Importance.HIGH,
                    chime=Chime.FAILURE,
                    icon='󰀦',
                    display_type=NotificationDisplayType.FLASH,
                ),
            ),
        )

    async def _request_voices(self, api_key: str) -> list[MistralVoiceEntry]:
        """Page through ``/v1/audio/voices`` and return the parsed entries."""
        headers = {'Authorization': f'Bearer {api_key}'}
        timeout = aiohttp.ClientTimeout(total=MISTRAL_VOICES_TIMEOUT_SECONDS)
        entries: list[MistralVoiceEntry] = []
        offset = 0
        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
        ) as session:
            for _ in range(MISTRAL_VOICES_MAX_PAGES):
                params = {
                    'type': 'all',
                    'limit': str(MISTRAL_VOICES_PAGE_SIZE),
                    'offset': str(offset),
                }
                async with session.get(
                    MISTRAL_VOICES_URL,
                    params=params,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json()
                entries.extend(_parse_voices_page(payload))
                total = payload.get('total') if isinstance(payload, dict) else None
                offset += MISTRAL_VOICES_PAGE_SIZE
                if not isinstance(total, int) or offset >= total:
                    break
        return entries

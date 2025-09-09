"""ElevenLabs engine interface."""

import re

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
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    QRCodeInputDescription,
    WebUIInputDescription,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils import secrets
from ubo_app.utils.input import ubo_input


class ElevenLabsEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """ElevenLabs engine."""

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
        secrets.write_secret(
            key=ELEVENLABS_VOICE_ID,
            value=result.data['voice_id'],
        )

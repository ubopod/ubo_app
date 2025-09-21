"""Rime TTS engine interface."""

import re

from typing_extensions import override

from ubo_app.constants.assistant import (
    RIME_API_KEY_PATTERN,
    RIME_API_KEY_SECRET_ID,
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


class RimeEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """Rime TTS engine."""

    @property
    def name(self) -> str:
        """The internal name of the Rime engine."""
        return 'rime'

    @property
    def label(self) -> str:
        """The display label for the Rime engine."""
        return 'Rime'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the Rime service API key is not set."""
        return 'Rime service API key is not set. You can set it in the settings.'

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the Rime engine is set up."""
        api_key = secrets.read_secret(RIME_API_KEY_SECRET_ID)
        return (
            bool(api_key)
            and re.match(RIME_API_KEY_PATTERN, api_key) is not None
        )

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='Rime API Key',
            prompt='Enter your Rime API key.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='API key',
                            description='Enter your Rime API key',
                            required=True,
                            pattern=RIME_API_KEY_PATTERN,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='Rime API Key',
                    instructions=ReadableInformation(
                        text='Convert your Rime API key to a QR code and hold it '
                        'in front of the camera to scan it.',
                        picovoice_text='Convert your Rime API key to a '
                        '{QR|K Y UW AA R} code and hold it in front of the camera '
                        'to scan it.',
                    ),
                    pattern=r'(?P<api_key>' + RIME_API_KEY_PATTERN + ')',
                ),
            ],
        )
        secrets.write_secret(
            key=RIME_API_KEY_SECRET_ID,
            value=result.data['api_key'],
        )

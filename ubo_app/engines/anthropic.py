"""Anthropic engine interface."""

import re

from typing_extensions import override

from ubo_app.constants.assistant import (
    ANTHROPIC_API_KEY_PATTERN,
    ANTHROPIC_API_KEY_SECRET_ID,
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


class AnthropicEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """Anthropic engine."""

    @property
    def name(self) -> str:
        """The internal name of the Anthropic engine."""
        return 'anthropic'

    @property
    def label(self) -> str:
        """The display label for the Anthropic engine."""
        return 'Anthropic'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the Anthropic service API key is not set."""
        return 'Anthropic service API key is not set. You can set it in the settings.'

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the Anthropic engine is set up."""
        api_key = secrets.read_secret(ANTHROPIC_API_KEY_SECRET_ID)
        return (
            bool(api_key)
            and re.match(ANTHROPIC_API_KEY_PATTERN, api_key) is not None
        )

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='Anthropic API Key',
            prompt='Enter your Anthropic API key.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='API Key',
                            description='Enter your Anthropic API key',
                            required=True,
                            pattern=ANTHROPIC_API_KEY_PATTERN,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='Anthropic API Key',
                    instructions=ReadableInformation(
                        text='Convert your Anthropic API key to a QR code and hold it '
                        'in front of the camera to scan it.',
                        picovoice_text='Convert your Anthropic API key to a '
                        '{QR|K Y UW AA R} code and hold it in front of the camera '
                        'to scan it.',
                    ),
                    pattern=r'(?P<api_key>' + ANTHROPIC_API_KEY_PATTERN + ')',
                ),
            ],
        )
        secrets.write_secret(
            key=ANTHROPIC_API_KEY_SECRET_ID,
            value=result.data['api_key'],
        )

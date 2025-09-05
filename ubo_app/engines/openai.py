"""OpenAI engine interface."""

import re

from typing_extensions import override

from ubo_app.constants.assistant import (
    OPENAI_API_KEY_PATTERN,
    OPENAI_API_KEY_SECRET_ID,
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


class OpenAIEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """OpenAI engine."""

    @property
    def name(self) -> str:
        """The internal name of the OpenAI engine."""
        return 'openai'

    @property
    def label(self) -> str:
        """The display label for the OpenAI engine."""
        return 'OpenAI'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the OpenAI service API key is not set."""
        return 'OpenAI service API key is not set. You can set it in the settings.'

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the OpenAI engine is set up."""
        service_account_info_string = secrets.read_secret(
            OPENAI_API_KEY_SECRET_ID,
        )
        return (
            bool(service_account_info_string)
            and re.match(
                OPENAI_API_KEY_PATTERN,
                service_account_info_string,
            )
            is not None
        )

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='OpenAI API Key',
            prompt='Enter your OpenAI API key.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='API key',
                            description='Enter your OpenAI API key',
                            required=True,
                            pattern=OPENAI_API_KEY_PATTERN,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='OpenAI API Key',
                    instructions=ReadableInformation(
                        text='Convert your OpenAI API key to a QR code and hold it in '
                        'front of the camera to scan it.',
                        picovoice_text='Convert your Open{AI|EY AY} API key to a '
                        '{QR|K Y UW AA R} code and hold it in front of the camera to '
                        'scan it.',
                    ),
                    pattern=r'(?P<api_key>' + OPENAI_API_KEY_PATTERN + ')',
                ),
            ],
        )
        secrets.write_secret(
            key=OPENAI_API_KEY_SECRET_ID,
            value=result.data['api_key'],
        )

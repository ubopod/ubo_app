"""Google engine interface."""

import re

from typing_extensions import override

from ubo_app.constants.assistant import (
    GOOGLE_API_KEY_PATTERN,
    GOOGLE_API_KEY_SECRET_ID,
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


class GoogleEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """Google engine."""

    @property
    def name(self) -> str:
        """The name of the Google engine."""
        return 'google'

    @property
    def label(self) -> str:
        """The label of the Google engine."""
        return 'Google'

    @property
    def not_setup_message(self) -> str:
        """The message to display when the Google engine is not set up."""
        return 'Google service API key is not set. You can set it in the settings.'

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the Google engine is set up."""
        service_account_info_string = secrets.read_secret(
            GOOGLE_API_KEY_SECRET_ID,
        )
        return (
            bool(service_account_info_string)
            and re.match(
                GOOGLE_API_KEY_PATTERN,
                service_account_info_string,
            )
            is not None
        )

    @override
    async def _setup(self) -> None:
        """Set up the Google engine."""
        _, result = await ubo_input(
            title='Google API Key',
            prompt='Enter your Google API key.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='API key',
                            description='Enter your Google AI Studio API key',
                            required=True,
                            pattern=GOOGLE_API_KEY_PATTERN,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='Google API Key',
                    instructions=ReadableInformation(
                        text='Convert your Google API key to a QR code and hold it in '
                        'front of the camera to scan it.',
                        picovoice_text='Convert your Google API key to a '
                        '{QR|K Y UW AA R} code and hold it in front of the camera to '
                        'scan it.',
                    ),
                    pattern=r'(?P<api_key>' + GOOGLE_API_KEY_PATTERN + ')',
                ),
            ],
        )
        secrets.write_secret(
            key=GOOGLE_API_KEY_SECRET_ID,
            value=result.data['api_key'],
        )

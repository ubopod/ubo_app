"""OpenAI engine implementation."""

import asyncio
import re

from typing_extensions import override

from ubo_app.constants import (
    OPENAI_API_KEY_PATTERN,
    OPENAI_API_KEY_SECRET_ID,
)
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    QRCodeInputDescription,
    WebUIInputDescription,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input


class OpenAIEngine(NeedsSetupMixin):
    """OpenAI engine."""

    _task: asyncio.Task[None] | None = None

    def __init__(self, name: str) -> None:
        """Initialize the OpenAI engine."""
        super().__init__(
            name=name,
            label='OpenAI',
            not_setup_message='OpenAI service API key is not set. You can '
            'set it in the settings.',
        )

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

    async def _setup_openai_api_key(self) -> None:
        _, result = await ubo_input(
            title='OpenAI API Key',
            prompt='Enter your OpenAI API key.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='Service Account Key',
                            description='Enter your OpenAI API key.',
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

    @override
    def setup(self) -> None:
        """Set up the OpenAI engine."""
        create_task(self._setup_openai_api_key())

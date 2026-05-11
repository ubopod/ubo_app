"""Qwen engine interface."""

import re

from typing_extensions import override

from ubo_app.constants.assistant import (
    QWEN_API_KEY_PATTERN,
    QWEN_API_KEY_SECRET_ID,
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


class QwenEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """Qwen (Alibaba DashScope) engine."""

    CURATED_MODELS = (
        'qwen-max',
        'qwen-plus',
        'qwen-turbo',
        'qwen2.5-72b-instruct',
        'qwen2.5-32b-instruct',
        'qwen2.5-coder-32b-instruct',
    )

    @property
    def name(self) -> str:
        """The internal name of the Qwen engine."""
        return 'qwen'

    @property
    def label(self) -> str:
        """The display label for the Qwen engine."""
        return 'Qwen'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the Qwen service API key is not set."""
        return 'Qwen service API key is not set. You can set it in the settings.'

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the Qwen engine is set up."""
        api_key = secrets.read_secret(QWEN_API_KEY_SECRET_ID)
        return (
            bool(api_key) and re.match(QWEN_API_KEY_PATTERN, api_key) is not None
        )

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='Qwen API Key',
            prompt='Enter your Qwen (DashScope) API key.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='API Key',
                            description='Enter your Qwen DashScope API key',
                            required=True,
                            pattern=QWEN_API_KEY_PATTERN,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='Qwen API Key',
                    instructions=ReadableInformation(
                        text='Convert your Qwen API key to a QR code and hold it '
                        'in front of the camera to scan it.',
                        picovoice_text='Convert your {Qwen|K W EH N} API key to a '
                        '{QR|K Y UW AA R} code and hold it in front of the camera '
                        'to scan it.',
                    ),
                    pattern=r'(?P<api_key>' + QWEN_API_KEY_PATTERN + ')',
                ),
            ],
        )
        secrets.write_secret(
            key=QWEN_API_KEY_SECRET_ID,
            value=result.data['api_key'],
        )

    @override
    def _clear_credentials(self) -> None:
        """Forget the Qwen API key."""
        secrets.clear_secret(QWEN_API_KEY_SECRET_ID)

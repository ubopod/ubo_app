"""DeepSeek engine interface."""

import re

from typing_extensions import override

from ubo_app.constants.assistant import (
    DEEPSEEK_API_KEY_PATTERN,
    DEEPSEEK_API_KEY_SECRET_ID,
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


class DeepSeekEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """DeepSeek engine."""

    CURATED_MODELS = (
        'deepseek-chat',
        'deepseek-reasoner',
    )

    @property
    def name(self) -> str:
        """The internal name of the DeepSeek engine."""
        return 'deepseek'

    @property
    def label(self) -> str:
        """The display label for the DeepSeek engine."""
        return 'DeepSeek'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the DeepSeek service API key is not set."""
        return 'DeepSeek service API key is not set. You can set it in the settings.'

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the DeepSeek engine is set up."""
        api_key = secrets.read_secret(DEEPSEEK_API_KEY_SECRET_ID)
        return (
            bool(api_key)
            and re.match(DEEPSEEK_API_KEY_PATTERN, api_key) is not None
        )

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='DeepSeek API Key',
            prompt='Enter your DeepSeek API key.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='API Key',
                            description='Enter your DeepSeek API key',
                            required=True,
                            pattern=DEEPSEEK_API_KEY_PATTERN,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='DeepSeek API Key',
                    instructions=ReadableInformation(
                        text='Convert your DeepSeek API key to a QR code and hold it '
                        'in front of the camera to scan it.',
                        picovoice_text='Convert your DeepSeek API key to a '
                        '{QR|K Y UW AA R} code and hold it in front of the camera '
                        'to scan it.',
                    ),
                    pattern=r'(?P<api_key>' + DEEPSEEK_API_KEY_PATTERN + ')',
                ),
            ],
        )
        secrets.write_secret(
            key=DEEPSEEK_API_KEY_SECRET_ID,
            value=result.data['api_key'],
        )

    @override
    def _clear_credentials(self) -> None:
        """Forget the DeepSeek API key."""
        secrets.clear_secret(DEEPSEEK_API_KEY_SECRET_ID)

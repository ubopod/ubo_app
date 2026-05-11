"""OpenRouter engine interface."""

import re

from typing_extensions import override

from ubo_app.constants.assistant import (
    OPENROUTER_API_KEY_PATTERN,
    OPENROUTER_API_KEY_SECRET_ID,
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


class OpenRouterEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """OpenRouter engine."""

    CURATED_MODELS = (
        'openrouter/auto',
        'openai/gpt-4o',
        'openai/gpt-4o-mini',
        'anthropic/claude-sonnet-4-5',
        'anthropic/claude-haiku-4-5',
        'google/gemini-2.5-flash',
        'meta-llama/llama-3.3-70b-instruct',
        'mistralai/mistral-large-2411',
        'deepseek/deepseek-chat',
        'qwen/qwen-2.5-72b-instruct',
    )

    @property
    def name(self) -> str:
        """The internal name of the OpenRouter engine."""
        return 'openrouter'

    @property
    def label(self) -> str:
        """The display label for the OpenRouter engine."""
        return 'OpenRouter'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the OpenRouter service API key is not set."""
        return 'OpenRouter service API key is not set. You can set it in the settings.'

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the OpenRouter engine is set up."""
        api_key = secrets.read_secret(OPENROUTER_API_KEY_SECRET_ID)
        return (
            bool(api_key)
            and re.match(OPENROUTER_API_KEY_PATTERN, api_key) is not None
        )

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='OpenRouter API Key',
            prompt='Enter your OpenRouter API key.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='API Key',
                            description='Enter your OpenRouter API key',
                            required=True,
                            pattern=OPENROUTER_API_KEY_PATTERN,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='OpenRouter API Key',
                    instructions=ReadableInformation(
                        text='Convert your OpenRouter API key to a QR code and hold '
                        'it in front of the camera to scan it.',
                        picovoice_text='Convert your OpenRouter API key to a '
                        '{QR|K Y UW AA R} code and hold it in front of the camera '
                        'to scan it.',
                    ),
                    pattern=r'(?P<api_key>' + OPENROUTER_API_KEY_PATTERN + ')',
                ),
            ],
        )
        secrets.write_secret(
            key=OPENROUTER_API_KEY_SECRET_ID,
            value=result.data['api_key'],
        )

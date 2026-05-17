"""Venice AI engine interface (OpenAI-compatible for LLM, STT and TTS)."""

import re

from typing_extensions import override

from ubo_app.constants.assistant import (
    VENICE_API_KEY_PATTERN,
    VENICE_API_KEY_SECRET_ID,
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


class VeniceEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """Venice AI engine — single class reused across LLM, STT and TTS dicts."""

    credential_secret_ids = (VENICE_API_KEY_SECRET_ID,)

    CURATED_MODELS = (
        'venice-uncensored',
        'qwen3-235b',
        'llama-3.3-70b',
        'mistral-31-24b',
        'qwen-2.5-vl',
    )

    @property
    def name(self) -> str:
        """The internal name of the Venice engine."""
        return 'venice'

    @property
    def label(self) -> str:
        """The display label for the Venice engine."""
        return 'Venice AI'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the Venice service API key is not set."""
        return 'Venice service API key is not set. You can set it in the settings.'

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the Venice engine is set up."""
        api_key = secrets.read_secret(VENICE_API_KEY_SECRET_ID)
        return (
            bool(api_key)
            and re.match(VENICE_API_KEY_PATTERN, api_key) is not None
        )

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='Venice API Key',
            prompt='Enter your Venice AI API key.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.TEXT,
                            label='API Key',
                            description='Enter your Venice AI API key',
                            required=True,
                            pattern=VENICE_API_KEY_PATTERN,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='Venice API Key',
                    instructions=ReadableInformation(
                        text='Convert your Venice API key to a QR code and hold it '
                        'in front of the camera to scan it.',
                        picovoice_text='Convert your {Venice|V EH N IH S} API key to a '
                        '{QR|K Y UW AA R} code and hold it in front of the camera to '
                        'scan it.',
                    ),
                    pattern=r'(?P<api_key>' + VENICE_API_KEY_PATTERN + ')',
                ),
            ],
        )
        secrets.write_secret(
            key=VENICE_API_KEY_SECRET_ID,
            value=result.data['api_key'],
        )

    @override
    def _clear_credentials(self) -> None:
        """Forget the Venice API key."""
        secrets.clear_secret(VENICE_API_KEY_SECRET_ID)

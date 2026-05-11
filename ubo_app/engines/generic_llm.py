"""Generic OpenAI-compatible LLM engine interface."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import aiohttp
from typing_extensions import override

from ubo_app.colors import WARNING_COLOR
from ubo_app.constants.assistant import (
    DEFAULT_LLM_GENERIC_MODEL,
    GENERIC_LLM_API_KEY_SECRET_ID,
    GENERIC_LLM_BASE_URL_PATTERN,
    GENERIC_LLM_BASE_URL_SECRET_ID,
    GENERIC_LLM_MODEL_SECRET_ID,
    GENERIC_LLM_SETUP_NOTIFICATION_ID,
)
from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
from ubo_app.logger import logger
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantLLMName,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedModelAction,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils import secrets
from ubo_app.utils.input import ubo_input

if TYPE_CHECKING:
    from collections.abc import Sequence

GENERIC_LLM_PROBE_TIMEOUT_SECONDS = 15


class GenericLLMEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """Generic OpenAI-compatible LLM engine."""

    credential_secret_ids = (
        GENERIC_LLM_BASE_URL_SECRET_ID,
        GENERIC_LLM_API_KEY_SECRET_ID,
        GENERIC_LLM_MODEL_SECRET_ID,
    )

    @property
    def name(self) -> AssistantLLMName:
        """The internal name of the Generic LLM engine."""
        return AssistantLLMName.GENERIC

    @property
    def label(self) -> str:
        """The display label for the Generic LLM engine."""
        return 'Generic LLM'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the Generic LLM service is not set up."""
        return 'Generic LLM endpoint is not set. You can set it in settings.'

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the Generic LLM engine is set up."""
        base_url = secrets.read_secret(GENERIC_LLM_BASE_URL_SECRET_ID)
        return bool(base_url) and re.match(GENERIC_LLM_BASE_URL_PATTERN, base_url) \
            is not None

    async def _list_models(
        self,
        *,
        base_url: str,
        api_key: str | None,
    ) -> Sequence[str]:
        """Probe an OpenAI-compatible endpoint and return available model IDs."""
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else None
        url = f'{base_url.rstrip("/")}/models'
        timeout = aiohttp.ClientTimeout(total=GENERIC_LLM_PROBE_TIMEOUT_SECONDS)

        async with (
            aiohttp.ClientSession(headers=headers, timeout=timeout) as session,
            session.get(url) as response,
        ):
            response.raise_for_status()
            payload = await response.json()

        models = payload.get('data', [])
        if not isinstance(models, list):
            return ()

        return tuple(
            model['id']
            for model in models
            if isinstance(model, dict) and isinstance(model.get('id'), str)
        )

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='Generic LLM',
            prompt='Enter your OpenAI-compatible LLM endpoint.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='base_url',
                            type=InputFieldType.TEXT,
                            label='Base URL',
                            description='Example: https://api.other-provider.com/v1',
                            required=True,
                            pattern=GENERIC_LLM_BASE_URL_PATTERN,
                        ),
                        InputFieldDescription(
                            name='api_key',
                            type=InputFieldType.PASSWORD,
                            label='API key',
                            description='Optional API key for this endpoint',
                        ),
                        InputFieldDescription(
                            name='model',
                            type=InputFieldType.TEXT,
                            label='Model',
                            description='Optional model name',
                        ),
                    ],
                ),
            ],
        )

        base_url = result.data['base_url'].strip().rstrip('/')
        api_key = result.data.get('api_key', '').strip()
        requested_model = result.data.get('model', '').strip()

        try:
            models = await self._list_models(
                base_url=base_url,
                api_key=api_key or None,
            )
        except Exception:
            logger.exception('Failed to probe Generic LLM endpoint')
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=GENERIC_LLM_SETUP_NOTIFICATION_ID,
                        title='Generic LLM Setup Failed',
                        content='Cannot connect to the OpenAI-compatible endpoint.',
                        color=WARNING_COLOR,
                        display_type=NotificationDisplayType.FLASH,
                    ),
                ),
            )
            return

        if requested_model and models and requested_model not in models:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=GENERIC_LLM_SETUP_NOTIFICATION_ID,
                        title='Generic LLM Setup Failed',
                        content='The requested model was not returned by the endpoint.',
                        color=WARNING_COLOR,
                        display_type=NotificationDisplayType.FLASH,
                    ),
                ),
            )
            return

        model = requested_model or next(iter(models), '')

        secrets.write_secret(key=GENERIC_LLM_BASE_URL_SECRET_ID, value=base_url)
        if api_key:
            secrets.write_secret(key=GENERIC_LLM_API_KEY_SECRET_ID, value=api_key)
        else:
            secrets.clear_secret(GENERIC_LLM_API_KEY_SECRET_ID)

        if model:
            secrets.write_secret(key=GENERIC_LLM_MODEL_SECRET_ID, value=model)
        else:
            secrets.clear_secret(GENERIC_LLM_MODEL_SECRET_ID)

        store.dispatch(
            AssistantSetSelectedModelAction(
                llm_name=AssistantLLMName.GENERIC,
                model=model or DEFAULT_LLM_GENERIC_MODEL,
            ),
        )
        store.dispatch(
            AssistantSetSelectedLLMAction(llm_name=AssistantLLMName.GENERIC),
        )

    @override
    def _clear_credentials(self) -> None:
        """Forget the Generic LLM endpoint, key and model."""
        secrets.clear_secret(GENERIC_LLM_BASE_URL_SECRET_ID)
        secrets.clear_secret(GENERIC_LLM_API_KEY_SECRET_ID)
        secrets.clear_secret(GENERIC_LLM_MODEL_SECRET_ID)

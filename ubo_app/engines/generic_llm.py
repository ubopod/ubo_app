"""Generic OpenAI-compatible LLM engine interface.

Two flavors share :class:`GenericLLMEngine`:

* The **adder** (no ``provider_id``) — a permanently-not-setup engine whose
  setup flow *adds* a new named provider. It lives in the static
  ``LLM_ENGINES`` registry under ``AssistantLLMName.GENERIC``.
* A **named instance** (``provider_id`` set) — one per provider the user (or
  a service such as the Hermes Docker composition) has registered. Instances
  are built dynamically from ``state.assistant.generic_llm_providers``.

Credentials live in the secrets file under per-provider keys
(``generic_llm_{provider_id}_base_url`` / ``_api_key`` / ``_model``).
Selecting a provider copies them into the canonical ``generic_llm_*`` keys
the assistant subprocess reads — see :func:`activate_provider`.
"""

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
    GENERIC_LLM_PROVIDER_API_KEY_SECRET_TEMPLATE,
    GENERIC_LLM_PROVIDER_BASE_URL_SECRET_TEMPLATE,
    GENERIC_LLM_PROVIDER_MODEL_SECRET_TEMPLATE,
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
    AssistantAddGenericLLMProviderAction,
    AssistantLLMName,
    AssistantRemoveGenericLLMProviderAction,
    AssistantSelectGenericLLMProviderAction,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedModelAction,
    GenericLLMProvider,
    generic_llm_instance_key,
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


def provider_secret_ids(provider_id: str) -> tuple[str, str, str]:
    """Return the (base_url, api_key, model) secret keys for a provider."""
    return (
        GENERIC_LLM_PROVIDER_BASE_URL_SECRET_TEMPLATE.format(provider_id=provider_id),
        GENERIC_LLM_PROVIDER_API_KEY_SECRET_TEMPLATE.format(provider_id=provider_id),
        GENERIC_LLM_PROVIDER_MODEL_SECRET_TEMPLATE.format(provider_id=provider_id),
    )


def slugify_provider_name(name: str) -> str:
    """Reduce a display name to a dotenv-safe provider id."""
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def activate_provider(provider_id: str) -> None:
    """Make *provider_id* the active generic LLM provider.

    Copies the provider's credentials into the canonical ``generic_llm_*``
    secret keys (the only ones the assistant subprocess queries), then
    dispatches the selection actions. The secret writes are synchronous, so
    they always land before the resulting events reach the subprocess.
    """
    base_url_key, api_key_key, model_key = provider_secret_ids(provider_id)
    base_url = secrets.read_secret(base_url_key)
    api_key = secrets.read_secret(api_key_key)
    model = secrets.read_secret(model_key)

    if not base_url:
        logger.warning(
            'Cannot activate generic LLM provider without a base URL',
            extra={'provider_id': provider_id},
        )
        return

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
        AssistantSelectGenericLLMProviderAction(provider_id=provider_id),
        AssistantSetSelectedModelAction(
            llm_name=AssistantLLMName.GENERIC,
            model=model or DEFAULT_LLM_GENERIC_MODEL,
        ),
        AssistantSetSelectedLLMAction(llm_name=AssistantLLMName.GENERIC),
    )


def clear_provider_secrets(provider_id: str, *, was_selected: bool) -> None:
    """Forget a removed provider's secrets (and canonical copies if active)."""
    for secret_id in provider_secret_ids(provider_id):
        secrets.clear_secret(secret_id)
    if was_selected:
        secrets.clear_secret(GENERIC_LLM_BASE_URL_SECRET_ID)
        secrets.clear_secret(GENERIC_LLM_API_KEY_SECRET_ID)
        secrets.clear_secret(GENERIC_LLM_MODEL_SECRET_ID)


def build_generic_llm_engines(
    providers: Sequence[GenericLLMProvider],
) -> dict[str, GenericLLMEngine]:
    """Build one engine instance per named generic LLM provider."""
    return {
        generic_llm_instance_key(provider.provider_id): GenericLLMEngine(
            provider_id=provider.provider_id,
            label=provider.label,
        )
        for provider in providers
    }


class GenericLLMEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """Generic OpenAI-compatible LLM engine (adder or named instance)."""

    def __init__(
        self,
        *,
        provider_id: str | None = None,
        label: str | None = None,
    ) -> None:
        """Initialize as the adder (no id) or as a named provider instance."""
        super().__init__(label=label)
        self.provider_id = provider_id
        if provider_id is not None:
            # Instance attribute shadows the class-level empty tuple so
            # ``has_stored_credentials`` and the credential-management UI
            # operate on this provider's own keys.
            self.credential_secret_ids = provider_secret_ids(provider_id)

    @property
    def name(self) -> str:
        """The internal name of this engine."""
        if self.provider_id is None:
            return AssistantLLMName.GENERIC
        return generic_llm_instance_key(self.provider_id)

    @property
    def label(self) -> str:
        """The display label for this engine."""
        if self.provider_id is None:
            return 'Add Generic LLM'
        # Menus reference ``label`` (not ``instance_label``) in several
        # places — surface the provider's name there too.
        return self._instance_label or 'Generic LLM'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the engine is not set up."""
        if self.provider_id is None:
            return 'Add a named OpenAI-compatible LLM provider in settings.'
        return (
            f'{self.instance_label} endpoint is not set. '
            'You can set it in settings.'
        )

    @property
    @override
    def is_setup(self) -> bool:
        """Check if this engine is set up.

        The adder is never "set up" — its setup flow is the add-provider
        flow, so it must always render as a setup action in menus.
        """
        if self.provider_id is None:
            return False
        base_url_key, _, _ = provider_secret_ids(self.provider_id)
        base_url = secrets.read_secret(base_url_key)
        return bool(base_url) and re.match(GENERIC_LLM_BASE_URL_PATTERN, base_url) \
            is not None

    @property
    def _notification_id(self) -> str:
        if self.provider_id is None:
            return GENERIC_LLM_SETUP_NOTIFICATION_ID
        return f'assistant:generic_llm:{self.provider_id}:setup'

    def _notify_failure(self, content: str) -> None:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=self._notification_id,
                    title='Generic LLM Setup Failed',
                    content=content,
                    color=WARNING_COLOR,
                    display_type=NotificationDisplayType.FLASH,
                ),
            ),
        )

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

    async def _collect_endpoint_input(
        self,
        *,
        with_name: bool,
    ) -> tuple[str, str, str, str] | None:
        """Run the input flow and validate the endpoint.

        Returns ``(name, base_url, api_key, model)`` (name is ``''`` when
        ``with_name`` is False) or ``None`` when validation/probing failed.
        """
        name_fields = (
            [
                InputFieldDescription(
                    name='name',
                    type=InputFieldType.TEXT,
                    label='Name',
                    description='A name for this provider, e.g. "My Server"',
                    required=True,
                ),
            ]
            if with_name
            else []
        )
        _, result = await ubo_input(
            title='Generic LLM',
            prompt='Enter your OpenAI-compatible LLM endpoint.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        *name_fields,
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

        name = result.data.get('name', '').strip()
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
            self._notify_failure('Cannot connect to the OpenAI-compatible endpoint.')
            return None

        if requested_model and models and requested_model not in models:
            self._notify_failure(
                'The requested model was not returned by the endpoint.',
            )
            return None

        model = requested_model or next(iter(models), '')
        return name, base_url, api_key, model

    @staticmethod
    def _write_provider_secrets(
        provider_id: str,
        *,
        base_url: str,
        api_key: str,
        model: str,
    ) -> None:
        base_url_key, api_key_key, model_key = provider_secret_ids(provider_id)
        secrets.write_secret(key=base_url_key, value=base_url)
        if api_key:
            secrets.write_secret(key=api_key_key, value=api_key)
        else:
            secrets.clear_secret(api_key_key)
        if model:
            secrets.write_secret(key=model_key, value=model)
        else:
            secrets.clear_secret(model_key)

    @store.with_state(lambda state: state.assistant.generic_llm_providers)
    def _existing_provider_ids(
        self,
        providers: tuple[GenericLLMProvider, ...],
    ) -> set[str]:
        return {provider.provider_id for provider in providers}

    @store.with_state(lambda state: state.assistant.selected_generic_llm_provider)
    def _is_selected_provider(self, selected: str) -> bool:
        return self.provider_id is not None and selected == self.provider_id

    async def _setup(self) -> None:
        if self.provider_id is None:
            await self._setup_add_provider()
        else:
            await self._setup_edit_provider()

    async def _setup_add_provider(self) -> None:
        """Add flow — collect a name + endpoint and register a new provider."""
        collected = await self._collect_endpoint_input(with_name=True)
        if collected is None:
            return
        name, base_url, api_key, model = collected

        provider_id = slugify_provider_name(name)
        if not provider_id:
            self._notify_failure('The provider name must contain letters or digits.')
            return
        if provider_id in self._existing_provider_ids():
            self._notify_failure(
                f'A provider named "{name}" already exists. '
                'Delete it first or pick another name.',
            )
            return

        self._write_provider_secrets(
            provider_id,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )
        store.dispatch(
            AssistantAddGenericLLMProviderAction(
                provider_id=provider_id,
                label=name,
            ),
        )
        activate_provider(provider_id)

    async def _setup_edit_provider(self) -> None:
        """Edit flow — update an existing provider's endpoint credentials."""
        if self.provider_id is None:  # pragma: no cover - guarded by _setup
            return
        collected = await self._collect_endpoint_input(with_name=False)
        if collected is None:
            return
        _, base_url, api_key, model = collected

        self._write_provider_secrets(
            self.provider_id,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )
        if self._is_selected_provider():
            # Re-activate so the canonical copies and the subprocess pick up
            # the new credentials.
            activate_provider(self.provider_id)

    @override
    def _clear_credentials(self) -> None:
        """Remove this provider — secrets cleanup happens in the event handler."""
        if self.provider_id is None:
            return
        store.dispatch(
            AssistantRemoveGenericLLMProviderAction(provider_id=self.provider_id),
        )

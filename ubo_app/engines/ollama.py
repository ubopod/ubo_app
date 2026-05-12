"""Ollama assistant engine module."""

from __future__ import annotations

import asyncio
import math

import ollama
from typing_extensions import override

from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.constants.assistant import OLLAMA_SETUP_NOTIFICATION_ID
from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.ollama_catalog import normalize_model_tag
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantLLMName,
    AssistantSetOllamaDownloadedModelsAction,
    AssistantSetSelectedModelAction,
    AssistantUpdateProvidersAction,
)
from ubo_app.store.services.docker import (
    DockerImageFetchAction,
    DockerImageRunAction,
    DockerItemStatus,
)
from ubo_app.store.services.notification_helpers import create_notification_action
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDispatchItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error


class OllamaEngine(NeedsSetupMixin, AIProviderMixin):
    """Ollama assistant engine."""

    # Shared async client. Reused across probes / refreshes / downloads so we
    # don't churn a fresh httpx connection pool (and the FDs it holds) on
    # every call.
    _async_client: ollama.AsyncClient | None = None

    @property
    def name(self) -> AssistantLLMName:
        """Returns the name identifier for the Ollama assistant."""
        return AssistantLLMName.OLLAMA

    @property
    def label(self) -> str:
        """Returns the display label for the Ollama assistant."""
        return 'Ollama'

    @property
    def not_setup_message(self) -> str:
        """Returns the message shown when Ollama is not set up."""
        return 'Ollama is not set up. Please set it up in the settings.'

    @property
    @override
    @store.with_state(
        lambda state: (
            state.assistant.selected_models[AssistantLLMName.OLLAMA],
            state.assistant.ollama_downloaded_models,
            state.assistant.ollama_downloaded_models_refreshed,
        ),
    )
    def is_setup(  # noqa: PLR0206
        self,
        data: tuple[str, tuple[str, ...], bool],
    ) -> bool:
        """Return True iff the selected model is in the cached download set.

        The cache is populated asynchronously by ``refresh_downloaded_models``
        — we deliberately don't call ``ollama.list()`` here because this
        property runs on the redux dispatch path (via ``@store.with_state``)
        and would block reducer + autorun work if the daemon were slow or
        unreachable.

        Before the first refresh completes (``refreshed=False``) we have no
        ground truth, so we trust the user's selection and report
        setup-complete. The next refresh dispatches
        ``AssistantUpdateProvidersAction`` which forces the icon autorun to
        re-evaluate against real data — avoiding a visible "not set up"
        flicker on every cold boot.
        """
        model, downloaded, refreshed = data
        if not refreshed:
            return bool(model)
        return normalize_model_tag(model) in downloaded

    def _client(self) -> ollama.AsyncClient:
        if OllamaEngine._async_client is None:
            OllamaEngine._async_client = ollama.AsyncClient()
        return OllamaEngine._async_client

    async def refresh_downloaded_models(self) -> None:
        """Poll the local daemon and cache its model set into the store.

        Safe to call from any context: never raises. Idempotent — only
        dispatches when the resulting set actually differs from what's
        already in the store, because every redundant dispatch otherwise
        cascades through the credential autoruns (each fire opens the
        secrets file once per credential-based engine on macOS) and pushes
        the process toward its FD limit.
        """
        try:
            result = await self._client().list()
        except Exception:
            logger.exception('Failed to query local Ollama daemon')
            normalised: tuple[str, ...] = ()
        else:
            normalised = tuple(
                normalize_model_tag(m.model)
                for m in result.models
                if m.model is not None
            )

        cached_models = self._cached_downloaded_models()
        cached_refreshed = self._cached_refreshed_flag()
        if cached_refreshed and frozenset(cached_models) == frozenset(normalised):
            return
        # Bundle the providers refresh with the cache update so the
        # ``provider_setup_status`` reducer re-evaluates ``is_setup`` against
        # the new cache — otherwise the gear→checkmark transition wouldn't
        # happen until the user incidentally triggered another
        # ``AssistantUpdateProvidersAction`` (e.g. by re-selecting the
        # provider).
        store.dispatch(
            AssistantSetOllamaDownloadedModelsAction(models=normalised),
            AssistantUpdateProvidersAction(),
        )

    @store.with_state(lambda state: state.assistant.ollama_downloaded_models)
    def _cached_downloaded_models(
        self,
        models: tuple[str, ...],
    ) -> tuple[str, ...]:
        return models

    @store.with_state(
        lambda state: state.assistant.ollama_downloaded_models_refreshed,
    )
    def _cached_refreshed_flag(
        self,
        refreshed: bool,  # noqa: FBT001
    ) -> bool:
        return refreshed

    def download_model(self, model: str) -> None:
        """Download *model* on the local Ollama daemon and update the store."""

        async def download_ollama_model() -> None:
            """Download Ollama model."""
            client = self._client()
            progress_notification = Notification(
                id=OLLAMA_SETUP_NOTIFICATION_ID,
                title='Ollama',
                content=f'Downloading {model} model',
                icon='󰇚',
                color=WARNING_COLOR,
                display_type=NotificationDisplayType.STICKY,
                progress=0,
                show_dismiss_action=False,
                dismiss_on_close=False,
                blink=False,
            )
            store.dispatch(NotificationsAddAction(notification=progress_notification))

            try:
                async for response in await client.pull(model, stream=True):
                    store.dispatch(
                        NotificationsAddAction(
                            notification=progress_notification(
                                progress=(response.completed / response.total)
                                if response.completed is not None
                                and response.total is not None
                                else math.nan,
                            ),
                        ),
                    )
            except Exception:
                logger.exception(
                    'Assistant - Error downloading Ollama model',
                    extra={'model': model},
                )
                report_service_error()
            else:
                logger.info(
                    'Ollama model download complete, updating providers',
                    extra={'model': model},
                )
                store.dispatch(
                    NotificationsAddAction(
                        notification=progress_notification(
                            content=f'"{model}" downloaded successfully',
                            icon='󰄬',
                            color=SUCCESS_COLOR,
                            display_type=NotificationDisplayType.FLASH,
                            progress=None,
                        ),
                    ),
                    AssistantSetSelectedModelAction(
                        llm_name=AssistantLLMName.OLLAMA,
                        model=model,
                    ),
                    AssistantUpdateProvidersAction(),
                )
                create_task(self._probe_and_dispatch_capabilities(model))
                create_task(self.refresh_downloaded_models())
            finally:
                event = getattr(self, 'event', None)
                if event is not None:
                    event.set()

        create_task(download_ollama_model())

    async def _probe_and_dispatch_capabilities(self, model: str) -> None:
        """Probe `client.show()` for *model* and cache its capability set.

        Idempotent: skips the dispatch entirely when the cached capability
        set already matches, for the same FD-pressure reasons as
        :meth:`refresh_downloaded_models`.
        """
        try:
            info = await self._client().show(model)
        except Exception:
            logger.exception(
                'Failed to probe Ollama model capabilities',
                extra={'model': model},
            )
            capabilities: tuple[str, ...] = ()
        else:
            raw = getattr(info, 'capabilities', None)
            if raw is None and isinstance(info, dict):
                raw = info.get('capabilities')
            capabilities = (
                tuple(str(c) for c in raw)
                if isinstance(raw, (list, tuple))
                else ()
            )

        cached = self._cached_capabilities().get(model)
        if cached is not None and frozenset(cached) == frozenset(capabilities):
            return

        from ubo_app.store.services.assistant import (
            AssistantSetOllamaModelCapabilitiesAction,
        )

        store.dispatch(
            AssistantSetOllamaModelCapabilitiesAction(
                model=model,
                capabilities=capabilities,
            ),
        )

    @store.with_state(lambda state: state.assistant.ollama_model_capabilities)
    def _cached_capabilities(
        self,
        caps: dict[str, tuple[str, ...]],
    ) -> dict[str, tuple[str, ...]]:
        return caps

    @store.with_state(
        lambda state: state.assistant.selected_models.get(
            AssistantLLMName.OLLAMA,
            '',
        ),
    )
    def _download_selected_model(self, model: str) -> None:
        """Notification-button entry point; downloads the currently-selected model."""
        if model:
            self.download_model(model)

    @override
    @store.with_state(
        lambda state: state.docker.ollama.status
        if hasattr(state, 'docker')
        else DockerItemStatus.NOT_AVAILABLE,
    )
    async def _setup(self, ollama_status: DockerItemStatus) -> None:
        if self.is_setup:
            return
        self.event = asyncio.Event()
        if ollama_status is DockerItemStatus.RUNNING:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=OLLAMA_SETUP_NOTIFICATION_ID,
                        title='Ollama Assistant Setup',
                        content='Setting up the Ollama assistant engine.',
                        color=WARNING_COLOR,
                        actions=[
                            create_notification_action(
                                label='Download Model',
                                icon='󰇚',
                                action=self._download_selected_model,
                            ),
                        ],
                    ),
                ),
            )
            await self.event.wait()
        elif ollama_status in (
            DockerItemStatus.NOT_AVAILABLE,
            DockerItemStatus.FETCHING,
        ):
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=OLLAMA_SETUP_NOTIFICATION_ID,
                        title='Ollama Assistant Setup',
                        content='The Ollama image is not fetched. It may take a while '
                        'to fetch, try again once download is complete.',
                        color=WARNING_COLOR,
                        actions=[
                            NotificationDispatchItem(
                                label='Download Ollama Image',
                                icon='󰇚',
                                store_action=DockerImageFetchAction(image='ollama'),
                            ),
                        ],
                    ),
                ),
            )
        else:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=OLLAMA_SETUP_NOTIFICATION_ID,
                        title='Ollama Assistant Setup',
                        content='The Ollama container is not running.',
                        color=WARNING_COLOR,
                        actions=[
                            NotificationDispatchItem(
                                label='Run Ollama Container',
                                icon='󰐊',
                                store_action=DockerImageRunAction(
                                    image='ollama',
                                ),
                            ),
                        ],
                    ),
                ),
            )

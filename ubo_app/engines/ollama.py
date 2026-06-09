"""Ollama assistant engine module."""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING

import ollama
from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Callable

from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.constants.assistant import (
    DEFAULT_LLM_OLLAMA_MODEL,
    OLLAMA_SETUP_NOTIFICATION_ID,
)
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
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error


def _ollama_status(state: object) -> DockerItemStatus:
    """Read the Ollama image status from the store, tolerating registration order.

    ``state.docker`` is a combine-reducer parent; individual images such as
    ``ollama`` are child reducers registered at runtime by the docker service.
    Until that registration lands, ``state.docker.ollama`` raises
    ``AttributeError``, so we guard with ``getattr`` (mirroring
    ``080-docker/menus.py``) and report ``NOT_AVAILABLE`` in the meantime.
    """
    docker = getattr(state, 'docker', None)
    ollama = getattr(docker, 'ollama', None)
    return ollama.status if ollama is not None else DockerItemStatus.NOT_AVAILABLE


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
            _ollama_status(state),
        ),
    )
    def is_setup(  # noqa: PLR0206
        self,
        data: tuple[str, tuple[str, ...], bool, DockerItemStatus],
    ) -> bool:
        """Return True iff Ollama is ready to serve the selected model.

        Readiness requires both the container to be RUNNING *and* the selected
        model to be present. Gating on the container status means stopping or
        removing it flips the engine back to "needs setup" (the run journey),
        keeping the menu in sync with the real container state.

        The downloaded-models set is populated asynchronously by
        ``refresh_downloaded_models`` — we deliberately don't call
        ``ollama.list()`` here because this property runs on the redux dispatch
        path (via ``@store.with_state``) and would block reducer + autorun work
        if the daemon were slow or unreachable.

        Before the first refresh completes (``refreshed=False``) we have no
        ground truth, so we trust the user's selection and report
        setup-complete. The next refresh dispatches
        ``AssistantUpdateProvidersAction`` which forces the icon autorun to
        re-evaluate against real data — avoiding a visible "not set up"
        flicker on every cold boot.
        """
        model, downloaded, refreshed, status = data
        if status is not DockerItemStatus.RUNNING:
            return False
        if not refreshed:
            return bool(model)
        return normalize_model_tag(model) in downloaded

    def _client(self) -> ollama.AsyncClient:
        if OllamaEngine._async_client is None:
            OllamaEngine._async_client = ollama.AsyncClient()
        return OllamaEngine._async_client

    async def refresh_downloaded_models(self) -> tuple[str, ...]:
        """Poll the local daemon and cache its model set into the store.

        Safe to call from any context: never raises. Idempotent — only
        dispatches when the resulting set actually differs from what's
        already in the store, because every redundant dispatch otherwise
        cascades through the credential autoruns (each fire opens the
        secrets file once per credential-based engine on macOS) and pushes
        the process toward its FD limit.

        Returns the freshly-fetched (normalised) model set so callers can act
        on the real daemon state without waiting for the dispatch above to
        commit to the store.
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
            return normalised
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
        return normalised

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

    @store.with_state(
        lambda state: state.assistant.selected_models.get(
            AssistantLLMName.OLLAMA,
            '',
        ),
    )
    def _selected_model(self, model: str) -> str:
        return model

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
        """Notification-button entry point; downloads the selected Ollama model.

        Falls back to ``DEFAULT_LLM_OLLAMA_MODEL`` when no model is selected
        (the stored selection can be empty), so the setup button never silently
        no-ops. ``download_model`` persists the selection on success via
        ``AssistantSetSelectedModelAction``, which lets ``is_setup`` flip true.
        """
        self.download_model(model or DEFAULT_LLM_OLLAMA_MODEL)

    @override
    @store.with_state(lambda state: _ollama_status(state))
    async def _setup(self, ollama_status: DockerItemStatus) -> None:
        if self.is_setup:
            return
        self._render_setup_notification(ollama_status)

    @store.with_state(lambda state: _ollama_status(state))
    def _docker_status(self, ollama_status: DockerItemStatus) -> DockerItemStatus:
        return ollama_status

    async def _wait_for_status(
        self,
        predicate: Callable[[DockerItemStatus], bool],
        *,
        max_wait: float,
        interval: float = 2.0,
    ) -> bool:
        """Poll the docker status until *predicate* holds, or ``max_wait`` elapses.

        Mirrors the bounded-poll approach the docker service itself uses in
        ``port_monitor.monitor_app_port``/``fetch_image``. Returns whether the
        predicate held by the time it stopped polling.
        """
        elapsed = 0.0
        while elapsed < max_wait:
            if predicate(self._docker_status()):
                return True
            await asyncio.sleep(interval)
            elapsed += interval
        return predicate(self._docker_status())

    def _fetch_ollama_image(self) -> None:
        """Pull the image, then advance the notification once it's available.

        Mirrors :meth:`_run_ollama_container`: the notification is re-rendered
        only after the docker status settles, so the user is moved on to the
        "run" step instead of being left on the "fetch" step (where re-pressing
        just re-pulls an already-present image).
        """

        async def fetch_then_continue() -> None:
            store.dispatch(DockerImageFetchAction(image='ollama'))
            # Image pulls can take minutes; the docker service shows its own
            # progress notification meanwhile. Wait until the image leaves the
            # not-fetched/fetching states (AVAILABLE on success, ERROR on
            # failure both end the wait).
            await self._wait_for_status(
                lambda status: status
                not in (
                    DockerItemStatus.NOT_AVAILABLE,
                    DockerItemStatus.FETCHING,
                ),
                max_wait=1800.0,
                interval=3.0,
            )
            self._render_setup_notification(self._docker_status())

        create_task(fetch_then_continue())

    def _run_ollama_container(self) -> None:
        """Start the container, then advance the notification once it is up.

        The notification is re-rendered only after the docker status settles —
        never in-place during the button press — so the press cannot race a
        swap of the notification's action button.
        """

        async def run_then_continue() -> None:
            store.dispatch(DockerImageRunAction(image='ollama'))
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=OLLAMA_SETUP_NOTIFICATION_ID,
                        title='Ollama Assistant Setup',
                        content='Starting the Ollama container…',
                        color=WARNING_COLOR,
                    ),
                ),
            )
            if await self._wait_for_status(
                lambda status: status is DockerItemStatus.RUNNING,
                max_wait=150.0,
            ):
                # The daemon is up now; query the real model list and skip the
                # redundant "Download Model" prompt only when the model that
                # would be downloaded is already present. Decided from the
                # returned set (not ``is_setup``) because the refresh dispatch
                # hasn't committed to the store yet.
                downloaded = await self.refresh_downloaded_models()
                effective_model = (
                    self._selected_model() or DEFAULT_LLM_OLLAMA_MODEL
                )
                if normalize_model_tag(effective_model) in downloaded:
                    store.dispatch(
                        NotificationsAddAction(
                            notification=Notification(
                                id=OLLAMA_SETUP_NOTIFICATION_ID,
                                title='Ollama Assistant Setup',
                                content='Ollama is ready.',
                                color=SUCCESS_COLOR,
                                display_type=NotificationDisplayType.FLASH,
                            ),
                        ),
                    )
                    return
            self._render_setup_notification(self._docker_status())

        create_task(run_then_continue())

    def _render_setup_notification(self, ollama_status: DockerItemStatus) -> None:
        if ollama_status is DockerItemStatus.RUNNING:
            # Reached only when a download is genuinely needed: the run chain
            # handles the already-present "ready" case before calling here, and
            # ``_setup`` only renders this branch when ``is_setup`` is False
            # (model absent).
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=OLLAMA_SETUP_NOTIFICATION_ID,
                        title='Ollama Assistant Setup',
                        content='Proceed to download the model.',
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
                            create_notification_action(
                                label='Download Ollama Image',
                                icon='󰇚',
                                action=self._fetch_ollama_image,
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
                            create_notification_action(
                                label='Run Ollama Container',
                                icon='󰐊',
                                action=self._run_ollama_container,
                            ),
                        ],
                    ),
                ),
            )

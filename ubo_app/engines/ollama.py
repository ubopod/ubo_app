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
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantLLMName,
    AssistantSetSelectedModelAction,
    AssistantUpdateProvidersAction,
)
from ubo_app.store.services.docker import (
    DockerImageFetchAction,
    DockerImageRunContainerAction,
    DockerItemStatus,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationDispatchItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error


class OllamaEngine(NeedsSetupMixin, AIProviderMixin):
    """Ollama assistant engine."""

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
        lambda state: state.assistant.selected_models[AssistantLLMName.OLLAMA],
    )
    def is_setup(self, model: str) -> bool:  # noqa: PLR0206
        try:
            models = ollama.list().models
        except ConnectionError:
            return False
        else:
            return any(m.model == model for m in models)

    @store.with_state(
        lambda state: state.assistant.selected_models[AssistantLLMName.OLLAMA],
    )
    def _download_model(self, model: str) -> None:
        """Download the specified Ollama model."""

        async def download_ollama_model() -> None:
            """Download Ollama model."""
            client = ollama.AsyncClient()
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
                    AssistantSetSelectedModelAction(model=model),
                    AssistantUpdateProvidersAction(),
                )
            finally:
                self.event.set()

        create_task(download_ollama_model())

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
                            NotificationActionItem(
                                label='Download Model',
                                icon='󰇚',
                                action=self._download_model,
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
                                store_action=DockerImageRunContainerAction(
                                    image='ollama',
                                ),
                            ),
                        ],
                    ),
                ),
            )

"""Ollama assistant engine module."""

from __future__ import annotations

import ollama
from typing_extensions import override

from ollama_engine.constants import SETUP_NOTIFICATION_ID
from ollama_engine.download_model import download_ollama_model
from ubo_app.colors import WARNING_COLOR
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.store.main import store
from ubo_app.store.services.assistant import AssistantLLMName
from ubo_app.store.services.docker import (
    DockerImageFetchAction,
    DockerImageRunContainerAction,
    DockerItemStatus,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationDispatchItem,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import create_task


class OllamaEngine(NeedsSetupMixin):
    """Ollama assistant engine."""

    def __init__(self) -> None:
        """Initialize the Ollama assistant engine."""
        super().__init__(
            name=AssistantLLMName.OLLAMA,
            label='Ollama',
            not_setup_message='Ollama is not set up. Please set it up in the settings.',
        )

    @override
    @store.with_state(
        lambda state: state.assistant.selected_models[AssistantLLMName.OLLAMA],
    )
    def is_setup(self, model: str) -> bool:
        try:
            models = ollama.list().models
        except ConnectionError:
            return False
        else:
            return any(m.model == model for m in models)

    @store.with_state(
        lambda state: state.assistant.selected_models[AssistantLLMName.OLLAMA],
    )
    async def download_model(self, model: str) -> None:
        """Download the specified Ollama model."""
        await download_ollama_model(model)
        self.setup()

    @override
    @store.with_state(
        lambda state: state.docker.ollama.status
        if hasattr(state, 'docker')
        else DockerItemStatus.NOT_AVAILABLE,
    )
    def setup(self, ollama_status: DockerItemStatus) -> None:
        if ollama_status is DockerItemStatus.RUNNING:
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=SETUP_NOTIFICATION_ID,
                        title='Ollama Assistant Setup',
                        content='Setting up the Ollama assistant engine.',
                        color=WARNING_COLOR,
                        actions=[
                            NotificationActionItem(
                                label='Download Model',
                                icon='󰇚',
                                action=lambda: create_task(self.download_model())
                                and None,
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
                        id=SETUP_NOTIFICATION_ID,
                        title='Ollama Assistant Setup',
                        content='The Ollama image is not fetched.',
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
                        id=SETUP_NOTIFICATION_ID,
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

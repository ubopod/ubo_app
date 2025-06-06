"""Ollama assistant engine module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ollama
from abstraction.text_processing_assistant_mixin import TextProcessingAssistantMixin
from typing_extensions import override

from ollama_engine.constants import SETUP_NOTIFICATION_ID
from ollama_engine.download_model import download_ollama_model
from ubo_app.colors import WARNING_COLOR
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.store.main import store
from ubo_app.store.services.assistant import AssistantEngineName
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

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class OllamaEngine(NeedsSetupMixin, TextProcessingAssistantMixin):
    """Ollama assistant engine."""

    def __init__(self) -> None:
        """Initialize the Ollama assistant engine."""
        super().__init__(
            name=AssistantEngineName.OLLAMA,
            label='Ollama',
            not_setup_message='Ollama is not set up. Please set it up in the settings.',
        )

    @override
    async def _run(self) -> None:
        """Run the Ollama assistant engine."""
        client = ollama.AsyncClient()

        @store.with_state(
            lambda state: state.assistant.selected_models[AssistantEngineName.OLLAMA],
        )
        async def process_text(
            model: str,
            text: str,
        ) -> AsyncIterator[ollama.ChatResponse]:
            """Process text using the Ollama model."""
            return await client.chat(
                model=model,
                stream=True,
                messages=[
                    {
                        'role': 'system',
                        'content': 'Please write short and concise answers.',
                    },
                    {
                        'role': 'system',
                        'content': """it is going to be read by a simple text to \
speech engine. So please answer only with English letters, numbers and standard \
production like period, comma, colon, single and double quotes, exclamation mark, \
question mark, and dash. Do not use any other special characters or emojis.""",
                    },
                    {'role': 'user', 'content': text},
                ],
            )

        while True:
            text = await self.input_queue.get()
            async for chunk in await process_text(text):
                chunk_text: str = chunk['message']['content']
                await self.report(chunk_text)
            await self.report('')

    @override
    @store.with_state(
        lambda state: state.assistant.selected_models[state.assistant.selected_engine],
    )
    def is_setup(self, model: str) -> bool:
        try:
            models = ollama.list().models
        except ConnectionError:
            return False
        else:
            return any(m.model == model for m in models)

    @store.with_state(
        lambda state: state.assistant.selected_models[AssistantEngineName.OLLAMA],
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

"""Ollama on-premise (remote) assistant engine module."""

from __future__ import annotations

import asyncio
import math
import re

import ollama
from typing_extensions import override

from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.constants.assistant import (
    OLLAMA_ONPREM_SETUP_NOTIFICATION_ID,
    OLLAMA_ONPREM_URL_PATTERN,
    OLLAMA_ONPREM_URL_SECRET_ID,
)
from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
from ubo_app.logger import logger
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    QRCodeInputDescription,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantLLMName,
    AssistantSetSelectedModelAction,
    AssistantUpdateProvidersAction,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.input import ubo_input


class OllamaOnPremEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """Ollama on-premise (remote) assistant engine."""

    @property
    def name(self) -> AssistantLLMName:
        """Returns the name identifier for the Ollama on-premise assistant."""
        return AssistantLLMName.OLLAMA_ONPREM

    @property
    def label(self) -> str:
        """Returns the display label for the Ollama on-premise assistant."""
        return 'Ollama (On-Prem)'

    @property
    def not_setup_message(self) -> str:
        """Returns the message shown when Ollama on-premise is not set up."""
        return 'Ollama on-premise URL is not set. Please configure it in settings.'

    @property
    @override
    @store.with_state(
        lambda state: (
            state.assistant.selected_models.get(
                AssistantLLMName.OLLAMA_ONPREM,
                '',
            ),
            secrets.read_secret(OLLAMA_ONPREM_URL_SECRET_ID) or '',
        ),
    )
    def is_setup(self, model_and_url: tuple[str, str]) -> bool:  # noqa: PLR0206
        """Check if the remote Ollama instance is accessible and has the model."""
        model, url = model_and_url
        if not url:
            return False

        try:
            client = ollama.Client(host=url)
            models = client.list().models
        except ConnectionError:
            return False
        except Exception:
            logger.exception(
                'Error checking remote Ollama setup',
                extra={'url': url},
            )
            return False
        else:
            return any(m.model == model for m in models)

    @store.with_state(
        lambda state: (
            state.assistant.selected_models.get(
                AssistantLLMName.OLLAMA_ONPREM,
                '',
            ),
            secrets.read_secret(OLLAMA_ONPREM_URL_SECRET_ID) or '',
        ),
    )
    def _download_model(self, model_and_url: tuple[str, str]) -> None:
        """Download the specified Ollama model on the remote instance."""
        model, url = model_and_url

        async def download_ollama_model() -> None:
            """Download Ollama model to remote instance."""
            client = ollama.AsyncClient(host=url)
            progress_notification = Notification(
                id=OLLAMA_ONPREM_SETUP_NOTIFICATION_ID,
                title='Ollama (On-Prem)',
                content=f'Downloading {model} model to remote instance',
                icon='󰇚',
                color=WARNING_COLOR,
                display_type=NotificationDisplayType.STICKY,
                progress=0,
                show_dismiss_action=False,
                dismiss_on_close=False,
                blink=False,
            )
            store.dispatch(
                NotificationsAddAction(notification=progress_notification),
            )

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
                    'Assistant - Error downloading Ollama model to remote '
                    'instance',
                    extra={'model': model, 'url': url},
                )
                report_service_error()
            else:
                logger.info(
                    'Ollama on-prem model download complete, updating providers',
                    extra={'model': model, 'url': url},
                )
                store.dispatch(
                    NotificationsAddAction(
                        notification=progress_notification(
                            content=(
                                f'"{model}" downloaded successfully to '
                                'remote instance'
                            ),
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
    async def _setup(self) -> None:
        """Set up the remote Ollama instance by getting the URL from user."""
        # First, check if we already have a URL configured
        existing_url = secrets.read_secret(OLLAMA_ONPREM_URL_SECRET_ID)

        if existing_url and re.match(
            OLLAMA_ONPREM_URL_PATTERN,
            existing_url,
        ):
            # URL exists, check if it's accessible and prompt for model
            # download
            try:
                client = ollama.Client(host=existing_url)
                client.list()  # Test connection

                # Connection successful, offer to download model
                if self.is_setup:
                    return

                self.event = asyncio.Event()
                store.dispatch(
                    NotificationsAddAction(
                        notification=Notification(
                            id=OLLAMA_ONPREM_SETUP_NOTIFICATION_ID,
                            title='Ollama On-Prem Setup',
                            content=(
                                'Connected to remote Ollama. Download a '
                                'model to continue.'
                            ),
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
            except ConnectionError:
                # Connection failed, prompt for new URL
                logger.debug(
                    'Failed to connect to existing Ollama URL',
                    extra={'url': existing_url},
                )
            except Exception:
                # Unexpected error, prompt for new URL
                logger.exception(
                    'Error checking existing Ollama URL',
                    extra={'url': existing_url},
                )
            else:
                # Connection successful and setup complete
                return

        # Prompt for URL configuration
        _, result = await ubo_input(
            title='Ollama On-Prem URL',
            prompt='Enter the URL of your remote Ollama instance.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='url',
                            type=InputFieldType.TEXT,
                            label='Ollama URL',
                            description=(
                                'Enter the URL '
                                '(e.g., http://192.168.1.100:11434)'
                            ),
                            required=True,
                            pattern=OLLAMA_ONPREM_URL_PATTERN,
                        ),
                    ],
                ),
                QRCodeInputDescription(
                    title='Ollama On-Prem URL',
                    instructions=ReadableInformation(
                        text=(
                            'Convert your Ollama URL to a QR code and '
                            'hold it in front of the camera to scan it.'
                        ),
                        picovoice_text=(
                            'Convert your Ollama URL to a '
                            '{QR|K Y UW AA R} code and hold it in '
                            'front of the camera to scan it.'
                        ),
                    ),
                    pattern=r'(?P<url>' + OLLAMA_ONPREM_URL_PATTERN + ')',
                ),
            ],
        )

        url = result.data['url']

        # Validate connection to the remote instance
        try:
            client = ollama.Client(host=url)
            client.list()  # Test connection
        except Exception:
            logger.exception(
                'Failed to connect to remote Ollama instance',
                extra={'url': url},
            )
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=OLLAMA_ONPREM_SETUP_NOTIFICATION_ID,
                        title='Ollama On-Prem Setup Failed',
                        content=(
                            f'Cannot connect to {url}. '
                            'Please verify the URL.'
                        ),
                        color=WARNING_COLOR,
                        display_type=NotificationDisplayType.FLASH,
                    ),
                ),
            )
            return

        # Save the URL
        secrets.write_secret(
            key=OLLAMA_ONPREM_URL_SECRET_ID,
            value=url,
        )

        # Prompt for model download
        if not self.is_setup:
            self.event = asyncio.Event()
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=OLLAMA_ONPREM_SETUP_NOTIFICATION_ID,
                        title='Ollama On-Prem Setup',
                        content=(
                            'Connected successfully. Download a model to '
                            'continue.'
                        ),
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

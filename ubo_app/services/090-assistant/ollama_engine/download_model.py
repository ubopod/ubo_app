"""Download Ollama model."""

from __future__ import annotations

import math
from dataclasses import replace

import ollama

from ollama_engine.constants import SETUP_NOTIFICATION_ID
from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.assistant import AssistantSetSelectedModelAction
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.error_handlers import report_service_error


async def download_ollama_model(model: str) -> None:
    """Download Ollama model."""
    client = ollama.AsyncClient()
    progress_notification = Notification(
        id=SETUP_NOTIFICATION_ID,
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
                    notification=replace(
                        progress_notification,
                        progress=(response.completed / response.total)
                        if response.completed is not None and response.total is not None
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
        return
    else:
        store.dispatch(
            NotificationsAddAction(
                notification=replace(
                    progress_notification,
                    content=f'"{model}" downloaded successfully',
                    icon='󰄬',
                    color=SUCCESS_COLOR,
                    display_type=NotificationDisplayType.FLASH,
                    progress=None,
                ),
            ),
            AssistantSetSelectedModelAction(model=model),
        )

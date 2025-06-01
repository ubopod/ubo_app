"""Implement `init_service` for assistant service."""

from __future__ import annotations

import math
import re
from dataclasses import replace
from typing import TYPE_CHECKING

import ollama
from redux import AutorunOptions
from ubo_gui.menu.types import HeadedMenu, SubMenuItem

from ubo_app.colors import SUCCESS_COLOR, WARNING_COLOR
from ubo_app.constants import DEFAULT_ASSISTANT_OLLAMA_MODEL
from ubo_app.logger import logger
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantDownloadOllamaModelAction,
    AssistantDownloadOllamaModelEvent,
    AssistantProcessSpeechEvent,
    AssistantSetActiveEngineAction,
)
from ubo_app.store.services.audio import AudioReportSampleEvent
from ubo_app.store.services.docker import (
    DockerImageFetchAction,
    DockerImageRunContainerAction,
    DockerItemStatus,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionReportTextEvent,
    SpeechRecognitionStatus,
)
from ubo_app.store.services.speech_synthesis import (
    ReadableInformation,
    SpeechSynthesisReadTextAction,
)
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.gui import SELECTED_ITEM_PARAMETERS, UNSELECTED_ITEM_PARAMETERS
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


async def download_ollama_model(event: AssistantDownloadOllamaModelEvent) -> None:
    """Download Ollama model."""
    client = ollama.AsyncClient()
    progress_notification = Notification(
        id='assistant:ollama_model_download',
        title='Ollama',
        content=f'Downloading {event.model} model',
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
        async for response in await client.pull(event.model, stream=True):
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
    except Exception:  # noqa: BLE001
        report_service_error()
        return
    else:
        store.dispatch(
            NotificationsAddAction(
                notification=replace(
                    progress_notification,
                    content=f'"{event.model}" downloaded successfully',
                    icon='󰄬',
                    color=SUCCESS_COLOR,
                    display_type=NotificationDisplayType.FLASH,
                    progress=None,
                ),
            ),
        )

        _engines_menu()


def _read_text(text: str) -> None:
    if not text.strip():
        return
    store.dispatch(
        SpeechSynthesisReadTextAction(
            information=ReadableInformation(text=text.replace('*', '')),
        ),
    )


@store.with_state(lambda state: state.assistant.active_engine)
async def process_complete_speech(
    active_engine: str,
    event: AssistantProcessSpeechEvent,
) -> None:
    """Process speech event."""
    if active_engine.startswith('ollama:'):
        active_engine = active_engine.partition(':')[2]
        client = ollama.AsyncClient()
        try:
            await client.show(active_engine)
        except Exception:  # noqa: BLE001
            report_service_error()

        evolving_text = ''
        response = await client.chat(
            model=active_engine,
            messages=[
                {
                    'role': 'system',
                    'content': """Please write short and concise answers.""",
                },
                {
                    'role': 'system',
                    'content': """it is going to be read by a simple text to speech \
engine. So please answer only with English letters, numbers and standard punctuation
like period, comma, colon, single and double quotes, exclamation mark, question mark, \
and dash. Do not use any other special characters or emojis.""",
                },
                {'role': 'user', 'content': event.text},
            ],
            stream=True,
        )
        async for chunk in response:
            chunk_text: str = chunk['message']['content']
            evolving_text += chunk_text
            logger.verbose(
                'Assistant - New chunk generated by ollama',
                extra={
                    'chunk': chunk_text,
                    'evolving_text': evolving_text,
                },
            )

            if matches := list(re.finditer(r'[.?!:;][\s\n]', evolving_text)):
                match = matches[-1]
                readable_text = evolving_text[: match.start() + 1]
                evolving_text = evolving_text[match.endpos :]
                logger.debug(
                    'Assistant - Enough text to read from ollama',
                    extra={
                        'readable_text': readable_text,
                        'evolving_text': evolving_text,
                    },
                )
                _read_text(readable_text)
        _read_text(evolving_text)
        logger.debug(
            'Assistant - Last text to read from ollama',
            extra={
                'text': evolving_text,
            },
        )
        return

    msg = f'Processing speech event is not implemented for {active_engine} engine'
    raise NotImplementedError(msg)


@store.with_state(lambda state: state.speech_recognition.status)
def process_audio_stream(
    status: SpeechRecognitionStatus,
    event: AudioReportSampleEvent,
) -> None:
    """Process audio stream event."""
    if status is SpeechRecognitionStatus.ASSISTANT_WAITING:
        _ = event


@store.with_state(lambda state: state.speech_recognition.status)
def process_text_stream(
    status: SpeechRecognitionStatus,
    event: SpeechRecognitionReportTextEvent,
) -> None:
    """Process text stream event."""
    if status is SpeechRecognitionStatus.ASSISTANT_WAITING:
        _ = event


@store.autorun(
    lambda state: (
        state.assistant.active_engine,
        state.docker.ollama.status,
    ),
    options=AutorunOptions(memoization=False),
)
def _engines_menu(data: tuple[str, DockerItemStatus | None]) -> HeadedMenu:
    [active_engine, ollama_status] = data
    try:
        ollama.ps()
    except ConnectionError:
        ollama_ready = False
    else:
        ollama_ready = True

    items = []

    if ollama_ready:
        models = sorted([model.model for model in ollama.list().models if model.model])
        items.extend(
            UboDispatchItem(
                key=model,
                label=model,
                store_action=AssistantSetActiveEngineAction(
                    engine=f'ollama:{model}',
                ),
                **(
                    SELECTED_ITEM_PARAMETERS
                    if active_engine == f'ollama:{model}'
                    else UNSELECTED_ITEM_PARAMETERS
                ),
            )
            for model in models
        )
        if DEFAULT_ASSISTANT_OLLAMA_MODEL not in models:
            items.append(
                UboDispatchItem(
                    key='ollama:_download',
                    label=f'Download {DEFAULT_ASSISTANT_OLLAMA_MODEL}',
                    icon='󰇚',
                    background_color=WARNING_COLOR,
                    store_action=AssistantDownloadOllamaModelAction(
                        model=DEFAULT_ASSISTANT_OLLAMA_MODEL,
                    ),
                ),
            )
    elif ollama_status in (DockerItemStatus.NOT_AVAILABLE, DockerItemStatus.FETCHING):
        items.append(
            UboDispatchItem(
                key='ollama:_start',
                label='Ollama Container',
                icon='󰇚',
                store_action=DockerImageFetchAction(image='ollama'),
            ),
        )
    else:
        items.append(
            UboDispatchItem(
                key='ollama:_start',
                label='Ollama Container',
                icon='󰐊',
                store_action=DockerImageRunContainerAction(image='ollama'),
            ),
        )

    return HeadedMenu(
        title='󰁤 Assistant Engine',
        heading='Assistant Engine',
        sub_heading=f'Active: {active_engine or "-"}',
        items=items,
    )


def init_service() -> Subscriptions:
    """Initialize the assistant service."""
    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.SPEECH,
            menu_item=SubMenuItem(
                label='Assistant Engine',
                icon='󰁤',
                sub_menu=_engines_menu,
            ),
        ),
    )
    register_persistent_store(
        'assistant:active_engine',
        lambda state: state.assistant.active_engine,
    )
    return [
        store.subscribe_event(AssistantProcessSpeechEvent, process_complete_speech),
        store.subscribe_event(AssistantDownloadOllamaModelEvent, download_ollama_model),
        store.subscribe_event(AudioReportSampleEvent, process_audio_stream),
        store.subscribe_event(SpeechRecognitionReportTextEvent, process_text_stream),
    ]

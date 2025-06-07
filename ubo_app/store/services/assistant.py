"""Definitions for assistant actions, events and state."""

from __future__ import annotations

from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.constants import (
    DEFAULT_ASSISTANT_GOOGLE_MODEL,
    DEFAULT_ASSISTANT_OLLAMA_MODEL,
)
from ubo_app.utils.persistent_store import read_from_persistent_store


class AssistantEngineName(StrEnum):
    """Available speech recognition engines."""

    OLLAMA = 'ollama'
    GOOGLE = 'google'


DEFAULT_MODELS = {
    AssistantEngineName.OLLAMA: DEFAULT_ASSISTANT_OLLAMA_MODEL,
    AssistantEngineName.GOOGLE: DEFAULT_ASSISTANT_GOOGLE_MODEL,
}


class AssistantAction(BaseAction):
    """Base class for assistant actions."""


class AssistantSetIsActiveAction(AssistantAction):
    """Action to set the assistant active state."""

    is_active: bool


class AssistantSetSelectedEngineAction(AssistantAction):
    """Action to set the selected engine."""

    engine_name: AssistantEngineName


class AssistantSetSelectedModelAction(AssistantAction):
    """Action to set the selected model."""

    model: str


class AssistantDownloadOllamaModelAction(AssistantAction):
    """Action to download an Ollama model."""

    model: str


class AssistantEvent(BaseEvent):
    """Base class for assistant events."""


class AssistantDownloadOllamaModelEvent(AssistantEvent):
    """Event to download an Ollama model."""

    model: str


class AssistantProcessSpeechEvent(AssistantEvent):
    """Event to process input speech."""

    audio: bytes
    text: str


class AssistantState(Immutable):
    """State for the assistant service."""

    is_active: bool = field(
        default=read_from_persistent_store(
            'assistant:is_active',
            default=False,
        ),
    )

    selected_engine: AssistantEngineName = field(
        default=read_from_persistent_store(
            'assistant:selected_engine',
            default=AssistantEngineName.OLLAMA,
            mapper=lambda value: AssistantEngineName(value)
            if value in AssistantEngineName.__members__
            else AssistantEngineName.OLLAMA,
        ),
    )
    selected_models: dict[AssistantEngineName, str] = field(
        default_factory=lambda: DEFAULT_MODELS,
    )

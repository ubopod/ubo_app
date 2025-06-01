"""Definitions for assistant actions, events and state."""

from __future__ import annotations

from dataclasses import field

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.constants import DEFAULT_ASSISTANT_OLLAMA_MODEL
from ubo_app.utils.persistent_store import read_from_persistent_store


class AssistantAction(BaseAction):
    """Base class for assistant actions."""


class AssistantSetSelectedEngineAction(AssistantAction):
    """Action to set the selected engine."""

    engine_name: str


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

    selected_engine: str = field(
        default_factory=lambda: read_from_persistent_store(
            'assistant:selected_engine',
            default=f'ollama:{DEFAULT_ASSISTANT_OLLAMA_MODEL}',
        ),
    )

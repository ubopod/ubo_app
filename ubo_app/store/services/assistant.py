"""Definitions for assistant actions, events and state."""

from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING, TypeAlias

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.constants import (
    DEFAULT_ASSISTANT_ANTHROPIC_MODEL,
    DEFAULT_ASSISTANT_GOOGLE_MODEL,
    DEFAULT_ASSISTANT_OLLAMA_MODEL,
    DEFAULT_ASSISTANT_OPENAI_MODEL,
)
from ubo_app.utils.persistent_store import read_from_persistent_store

if TYPE_CHECKING:
    from ubo_app.store.services.audio import AudioSample


class AssistantLLMName(StrEnum):
    """Available assistant llms."""

    OLLAMA = 'ollama'
    GOOGLE = 'google'
    OPENAI = 'openai'
    ANTHROPIC = 'anthropic'


DEFAULT_MODELS = {
    AssistantLLMName.OLLAMA: DEFAULT_ASSISTANT_OLLAMA_MODEL,
    AssistantLLMName.GOOGLE: DEFAULT_ASSISTANT_GOOGLE_MODEL,
    AssistantLLMName.OPENAI: DEFAULT_ASSISTANT_OPENAI_MODEL,
    AssistantLLMName.ANTHROPIC: DEFAULT_ASSISTANT_ANTHROPIC_MODEL,
}


class AssistantAction(BaseAction):
    """Base class for assistant actions."""


class AssistantSetIsActiveAction(AssistantAction):
    """Action to set the assistant active state."""

    is_active: bool


class AssistantSetSelectedLLMAction(AssistantAction):
    """Action to set the selected llm."""

    llm_name: AssistantLLMName


class AssistantSetSelectedModelAction(AssistantAction):
    """Action to set the selected model."""

    model: str


class AssistantDownloadOllamaModelAction(AssistantAction):
    """Action to download an Ollama model."""

    model: str


class AssistanceFrame(Immutable):
    """An assistance frame."""

    is_last_frame: bool
    timestamp: float
    id: str
    index: int


class AssistanceTextFrame(AssistanceFrame):
    """A text assistance frame."""

    text: str | None


class AssistanceAudioFrame(AssistanceFrame):
    """An audio assistance frame."""

    audio: AudioSample | None


class AssistanceImageFrame(AssistanceFrame):
    """An image assistance frame."""

    image: bytes | None = None


class AssistanceVideoFrame(AssistanceFrame):
    """An video assistance frame."""

    video: bytes | None = None


AcceptableAssistanceFrame: TypeAlias = (
    AssistanceTextFrame
    | AssistanceAudioFrame
    | AssistanceImageFrame
    | AssistanceVideoFrame
)


class AssistantReportAction(AssistantAction):
    """Action to report assistance from the assistant."""

    source_id: str
    data: AcceptableAssistanceFrame


class AssistantStartListeningAction(AssistantAction):
    """Action to start listening for the assistant."""


class AssistantStopListeningAction(AssistantAction):
    """Action to stop listening for the assistant."""


class AssistantEvent(BaseEvent):
    """Base class for assistant events."""


class AssistantDownloadOllamaModelEvent(AssistantEvent):
    """Event to download an Ollama model."""

    model: str


class AssistantReportEvent(AssistantEvent):
    """Action to report assistance from the assistant."""

    source_id: str
    data: AcceptableAssistanceFrame


class AssistantState(Immutable):
    """State for the assistant service."""

    is_listening: bool = False
    is_active: bool = field(
        default=read_from_persistent_store(
            'assistant:is_active',
            default=False,
        ),
    )
    selected_llm: AssistantLLMName = field(
        default=read_from_persistent_store(
            'assistant:selected_llm',
            default=AssistantLLMName.OLLAMA,
            mapper=lambda value: AssistantLLMName(value)
            if value in AssistantLLMName.__members__
            else AssistantLLMName.OLLAMA,
        ),
    )
    selected_models: dict[AssistantLLMName, str] = field(
        default_factory=lambda: DEFAULT_MODELS,
    )

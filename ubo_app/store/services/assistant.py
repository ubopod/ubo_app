"""Definitions for assistant actions, events and state."""

from __future__ import annotations

import json
from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING, TypeAlias

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.constants.assistant import (
    DEFAULT_LLM_CEREBRAS_MODEL,
    DEFAULT_LLM_GOOGLE_MODEL,
    DEFAULT_LLM_GROK_MODEL,
    DEFAULT_LLM_OLLAMA_MODEL,
    DEFAULT_LLM_OLLAMA_ONPREM_MODEL,
    DEFAULT_LLM_OPENAI_MODEL,
)
from ubo_app.utils.persistent_store import read_from_persistent_store

if TYPE_CHECKING:
    from ubo_app.store.services.audio import AudioSample


class AssistantSTTName(StrEnum):
    """Available assistant speech-to-text engines."""

    VOSK = 'vosk'
    GOOGLE_SEGMENTED = 'google_segmented'
    GOOGLE = 'google'
    OPENAI = 'openai'
    DEEPGRAM = 'deepgram'
    ASSEMBLYAI = 'assemblyai'


class AssistantLLMName(StrEnum):
    """Available assistant llms."""

    OLLAMA = 'ollama'
    OLLAMA_ONPREM = 'ollama_onprem'
    GOOGLE = 'google_vertex'
    OPENAI = 'openai'
    GROK = 'grok'
    CEREBRAS = 'cerebras'


DEFAULT_MODELS = {
    AssistantLLMName.OLLAMA: DEFAULT_LLM_OLLAMA_MODEL,
    AssistantLLMName.OLLAMA_ONPREM: DEFAULT_LLM_OLLAMA_ONPREM_MODEL,
    AssistantLLMName.GOOGLE: DEFAULT_LLM_GOOGLE_MODEL,
    AssistantLLMName.OPENAI: DEFAULT_LLM_OPENAI_MODEL,
    AssistantLLMName.GROK: DEFAULT_LLM_GROK_MODEL,
    AssistantLLMName.CEREBRAS: DEFAULT_LLM_CEREBRAS_MODEL,
}


class AssistantTTSName(StrEnum):
    """Available assistant text-to-speech engines."""

    PIPER = 'piper'
    GOOGLE = 'google'
    OPENAI = 'openai'
    ELEVENLABS = 'elevenlabs'
    RIME = 'rime'


class AssistantImageGeneratorName(StrEnum):
    """Available assistant image generator engines."""

    GOOGLE = 'google'
    OPENAI = 'openai'


class McpServerType(StrEnum):
    """MCP server types."""

    STDIO = 'stdio'
    SSE = 'sse'


class McpServerMetadata(Immutable):
    """Metadata for an MCP server."""

    server_id: str  # Format: {name}_{uuid}
    name: str  # User-friendly name
    type: McpServerType  # Server type enum
    config: str  # JSON string for stdio, URL string for sse


class AssistantAction(BaseAction):
    """Base class for assistant actions."""


class AssistantSetIsActiveAction(AssistantAction):
    """Action to set the assistant active state."""

    is_active: bool


class AssistantSetSelectedSTTAction(AssistantAction):
    """Action to set the selected stt."""

    stt_name: AssistantSTTName


class AssistantSetSelectedLLMAction(AssistantAction):
    """Action to set the selected llm."""

    llm_name: AssistantLLMName


class AssistantSetSelectedTTSAction(AssistantAction):
    """Action to set the selected tts."""

    tts_name: AssistantTTSName


class AssistantSetSelectedImageGeneratorAction(AssistantAction):
    """Action to set the selected image generator."""

    image_generator_name: AssistantImageGeneratorName


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

    text: str


class AssistanceAudioFrame(AssistanceFrame):
    """An audio assistance frame."""

    audio: AudioSample | None


class AssistanceImageFrame(AssistanceFrame):
    """An image assistance frame."""

    image: bytes
    width: int
    height: int
    format: str
    metadata: dict[str, str]


AcceptableAssistanceFrame: TypeAlias = (
    AssistanceTextFrame | AssistanceAudioFrame | AssistanceImageFrame
)


class AssistantReportAction(AssistantAction):
    """Action to report assistance from the assistant."""

    source_id: str
    data: AcceptableAssistanceFrame


class AssistantStartListeningAction(AssistantAction):
    """Action to start listening for the assistant."""


class AssistantStopListeningAction(AssistantAction):
    """Action to stop listening for the assistant."""


class AssistantToggleListeningAction(AssistantAction):
    """Action to toggle listening state for the assistant."""


class AssistantUpdateProvidersAction(AssistantAction):
    """Action to signal change in the state of available providers."""


class AssistantAddMcpServerAction(AssistantAction):
    """Action to add a new MCP server."""

    name: str
    type: McpServerType
    config: str  # JSON string for stdio, URL string for sse


class AssistantToggleMcpServerAction(AssistantAction):
    """Action to enable/disable an MCP server."""

    server_id: str


class AssistantDeleteMcpServerAction(AssistantAction):
    """Action to delete an MCP server."""

    server_id: str


class AssistantSyncMcpServersAction(AssistantAction):
    """Action to sync MCP servers from filesystem."""


class AssistantEvent(BaseEvent):
    """Base class for assistant events."""


class AssistantDownloadOllamaModelEvent(AssistantEvent):
    """Event to download an Ollama model."""

    model: str


class AssistantHandleReportEvent(AssistantEvent):
    """Action to report assistance from the assistant."""

    source_id: str
    data: AcceptableAssistanceFrame


class AssistantUpdateProvidersEvent(AssistantEvent):
    """Event to signal change in the state of available providers."""


class AssistantAddMcpServerEvent(AssistantEvent):
    """Event to add a new MCP server."""

    name: str
    type: McpServerType
    config: str  # JSON string for stdio, URL string for sse


class AssistantDeleteMcpServerEvent(AssistantEvent):
    """Event to delete an MCP server."""

    server_id: str


class AssistantState(Immutable):
    """State for the assistant service."""

    is_listening: bool = False
    is_microphone_mute: bool = False
    is_active: bool = field(
        default=read_from_persistent_store(
            'assistant:is_active',
            default=False,
        ),
    )
    selected_stt: AssistantSTTName = field(
        default=read_from_persistent_store(
            'assistant:selected_stt',
            default=AssistantSTTName.VOSK,
            mapper=lambda value: AssistantSTTName(value)
            if value in AssistantSTTName.__members__.values()
            else AssistantSTTName.VOSK,
        ),
    )
    selected_llm: AssistantLLMName = field(
        default=read_from_persistent_store(
            'assistant:selected_llm',
            default=AssistantLLMName.OLLAMA,
            mapper=lambda value: AssistantLLMName(value)
            if value in AssistantLLMName.__members__.values()
            else AssistantLLMName.OLLAMA,
        ),
    )
    selected_models: dict[AssistantLLMName, str] = field(
        default_factory=lambda: read_from_persistent_store(
            'assistant:selected_llm_model',
            default=DEFAULT_MODELS,
            mapper=json.loads,
        ),
    )
    selected_tts: AssistantTTSName = field(
        default=read_from_persistent_store(
            'assistant:selected_tts',
            default=AssistantTTSName.PIPER,
            mapper=lambda value: AssistantTTSName(value)
            if value in AssistantTTSName.__members__.values()
            else AssistantTTSName.PIPER,
        ),
    )
    selected_image_generator: AssistantImageGeneratorName = field(
        default=read_from_persistent_store(
            'assistant:selected_image_generator',
            default=AssistantImageGeneratorName.GOOGLE,
            mapper=lambda value: AssistantImageGeneratorName(value)
            if value in AssistantImageGeneratorName.__members__.values()
            else AssistantImageGeneratorName.GOOGLE,
        ),
    )
    mcp_servers: dict[str, McpServerMetadata] = field(default_factory=dict)
    enabled_mcp_servers: list[str] = field(
        default_factory=lambda: read_from_persistent_store(
            'assistant:enabled_mcp_servers',
            default=[],
            mapper=lambda value: json.loads(value)
            if isinstance(value, str)
            else list(value),
        ),
    )
    # JSON string for gRPC autorun - enabled servers with full metadata
    enabled_mcp_servers_with_metadata_json: str = '[]'
    # Setup status for all provider engines - source of truth for UI
    provider_setup_status: dict[str, bool] = field(default_factory=dict)

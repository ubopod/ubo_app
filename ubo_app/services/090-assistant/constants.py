"""Constants for the Assistant service."""

from ubo_app.store.services.assistant import AssistantLLMName

AUDIO_PROCESSING_ENGINES: list[AssistantLLMName] = []
OFFLINE_ENGINES: list[AssistantLLMName] = [AssistantLLMName.OLLAMA]

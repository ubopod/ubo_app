"""Constants for the Assistant service."""

from ubo_app.store.services.assistant import AssistantEngineName

AUDIO_PROCESSING_ENGINES: list[AssistantEngineName] = []
OFFLINE_ENGINES: list[AssistantEngineName] = [AssistantEngineName.OLLAMA]

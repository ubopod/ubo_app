"""Sync store with assistant engines."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from abstraction.text_processing_assistant_mixin import TextProcessingAssistantMixin
from ollama_engine import OllamaEngine

from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantEngineName,
    AssistantProcessSpeechEvent,
)
from ubo_app.store.services.speech_synthesis import (
    ReadableInformation,
    SpeechSynthesisReadTextAction,
)
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from abstraction.assistant_mixin import AssistantMixin

    from ubo_app.utils.types import Subscriptions


class EnginesManager:
    """Manager for speech recognition engines."""

    def __init__(self) -> None:
        """Initialize `EnginesManager`."""
        ollama_engine = OllamaEngine()
        self.engines_by_name: dict[AssistantEngineName, AssistantMixin] = {
            AssistantEngineName.OLLAMA: ollama_engine,
        }
        self.selected_engine: AssistantMixin | None = None

        store.autorun(lambda state: state.assistant.selected_engine)(
            self._sync_selected_engine,
        )

        create_task(
            self._monitor_speech_recognitions(),
            name='SpeechRecognitionMonitor',
        )

        self.subscriptions: Subscriptions = [
            store.subscribe_event(AssistantProcessSpeechEvent, self._queue_speech),
            self._cleanup,
        ]

    async def _queue_speech(self, event: AssistantProcessSpeechEvent) -> None:
        """Queue speech to the selected assistant engine."""
        if isinstance(self.selected_engine, TextProcessingAssistantMixin):
            await self.selected_engine.activate_assistance()
            await self.selected_engine.queue_text(event.text)

    async def _sync_selected_engine(
        self,
        selected_engine: AssistantEngineName | None,
    ) -> None:
        """Sync selected assistant engine."""
        if self.selected_engine is not None:
            await self.selected_engine.deactivate_assistance()
        self.selected_engine = (
            self.engines_by_name[selected_engine] if selected_engine else None
        )

    async def _monitor_speech_recognitions(self) -> None:
        """Monitor speech recognitions and handle them."""
        while True:
            if self.selected_engine is not None:
                async for assistance in self.selected_engine.assistances():
                    store.dispatch(
                        SpeechSynthesisReadTextAction(
                            information=ReadableInformation(text=assistance.text),
                        ),
                    )
            await asyncio.sleep(0.1)

    def _cleanup(self) -> None:
        """Cleanup function to stop all engines."""
        if self.selected_engine:
            self.selected_engine.stop()

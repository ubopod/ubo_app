"""Text Processing Assistant Mixin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override

from abstraction.assistant_mixin import AssistantMixin
from ubo_app.logger import logger
from ubo_app.utils.async_evicting_queue import AsyncEvictingQueue

if TYPE_CHECKING:
    from ubo_app.store.services.assistant import AssistantEngineName


class TextProcessingAssistantMixin(AssistantMixin):
    """Mixin for text processing assistants."""

    def __init__(self, name: AssistantEngineName, label: str) -> None:
        """Initialize the text processing assistant mixin."""
        self.input_queue: AsyncEvictingQueue[str] = AsyncEvictingQueue(maxsize=5)
        super().__init__(name=name, label=label)

    async def queue_text(self, text: str) -> None:
        """Queue text for processing by the assistant engine."""
        await self.input_queue.put(text)

    @override
    async def report(self, result: str) -> None:
        """Report the assistance."""
        logger.info(
            'Assistance',
            extra={
                'result': result,
                'engine_name': self.name,
            },
        )
        if self.ongoing_assistance:
            if not result:
                await self._complete_assistance()
            else:
                self.ongoing_assistance.append_text(result)
        else:
            await super().report(result)

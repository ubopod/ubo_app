"""Assistant mixin abstract base class."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_extensions import override

from ubo_app.engines.abstraction.background_running_mixin import BackgroundRunningMixin
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.assistant import AssistantSetIsActiveAction
from ubo_app.utils.async_evicting_queue import AsyncEvictingQueue

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ubo_app.store.services.assistant import AssistantEngineName


class Assistance:
    """Base class for assistance data."""

    def __init__(self, engine_name: AssistantEngineName) -> None:
        """Initialize an assistance instance."""
        self.audio = b''
        self.text = ''
        self.engine_name = engine_name

    def append_voice(self, data: bytes) -> None:
        """Append a chunk of audio data to the ongoing assistance."""
        self.audio += data

    def append_text(self, text: str) -> None:
        """Append text to the ongoing assistance."""
        self.text += text


class AssistantMixin(BackgroundRunningMixin):
    """Base class for assistant engines."""

    assistant_engine_name: AssistantEngineName

    @override
    def __init__(self, *, name: AssistantEngineName, label: str) -> None:
        """Initialize speech recognition engine."""
        self.ongoing_assistance: Assistance | None = None
        self.assistance_queue: AsyncEvictingQueue[Assistance | None] = (
            AsyncEvictingQueue(maxsize=5)
        )
        self.assistant_engine_name = name
        super().__init__(name=name, label=label)

    @override
    def run(self) -> bool:
        if not super().run():
            store.dispatch(AssistantSetIsActiveAction(is_active=False))
            return False
        return True

    def should_be_running(self) -> bool:
        """Check if the assistant engine should be running."""
        return self.ongoing_assistance is not None or super().should_be_running()

    @final
    async def activate_assistance(self) -> None:
        """Activate speech recognition."""
        if self.ongoing_assistance is not None:
            msg = 'Assistance is already active.'
            raise RuntimeError(msg)
        self.ongoing_assistance = Assistance(self.assistant_engine_name)

        self.decide_running_state()

    @final
    async def deactivate_assistance(self) -> None:
        """Deactivate the ongoing speech recognition."""
        self.ongoing_assistance = None
        await self.assistance_queue.put(None)

        self.decide_running_state()

    @final
    async def _complete_assistance(self) -> None:
        """Complete the ongoing speech recognition."""
        if self.ongoing_assistance is None:
            msg = 'Assistance is not active.'
            raise RuntimeError(msg)
        await self.assistance_queue.put(self.ongoing_assistance)
        await self.deactivate_assistance()

    async def report(self, result: str) -> None:
        """Report the assistance."""
        logger.debug(
            'Unprocessed assistance',
            extra={
                'result': result,
                'engine_name': self.name,
            },
        )

    @final
    async def assistances(self) -> AsyncGenerator[Assistance, None]:
        """Yield assistances."""
        while assistance := await self.assistance_queue.get():
            yield assistance

"""Wake word recognition mixin abstract base class."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, NamedTuple, final

from typing_extensions import override

from ubo_app.utils.async_evicting_queue import AsyncEvictingQueue

from .base_class import BaseSpeechRecognitionEngine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence


class WakeTrigger(NamedTuple):
    """A single thing an engine listens for.

    ``id`` is the stable trigger id (the detection queue carries it so the reducer
    can resolve the trigger's mode); ``value`` is the engine-specific match string
    (a phrase for Vosk, a model stem for OpenWakeWord). ``sensitivity`` (0.0-1.0)
    is how readily a confidence-scored engine fires; phrase-match engines ignore it.
    """

    id: str
    value: str
    sensitivity: float = 0.5


class WakeWordRecognitionMixin(BaseSpeechRecognitionEngine, abc.ABC):
    """Mixin for wake word detection functionality."""

    triggers: Sequence[WakeTrigger] = ()

    @override
    def __init__(self, *, label: str | None = None) -> None:
        """Initialize wake word recognition mixin."""
        self.triggers = ()
        # The queue carries *trigger ids*, not phrases.
        self.woke_word_recognitions_queue: AsyncEvictingQueue[str | None] = (
            AsyncEvictingQueue(maxsize=5)
        )
        super().__init__(label=label)

    @property
    def wake_words(self) -> list[str]:
        """The match values of the configured triggers (e.g. the Vosk grammar)."""
        return [trigger.value for trigger in self.triggers]

    def set_triggers(self, triggers: Sequence[WakeTrigger] | None) -> None:
        """Set the wake-word triggers this engine should listen for."""
        from ubo_app.logger import logger

        self.triggers = tuple(triggers) if triggers else ()
        logger.debug(
            'Setting wake-word triggers',
            extra={'engine_name': self.name, 'trigger_count': len(self.triggers)},
        )
        self.decide_running_state()

    @final
    async def wake_word_recogntions(self) -> AsyncGenerator[str, None]:
        """Yield the ids of recognized wake-word triggers."""
        while trigger_id := await self.woke_word_recognitions_queue.get():
            yield trigger_id

    @override
    async def report(self, result: str) -> None:
        """Report recognized speech and queue any matching trigger's id."""
        lowered = result.lower()
        for trigger in self.triggers:
            if trigger.value.lower() in lowered:
                await self.woke_word_recognitions_queue.put(trigger.id)
                break
        else:
            await super().report(result)

    @override
    def should_be_running(self) -> bool:
        """Check if the wake word engine should be running."""
        return bool(self.triggers) or super().should_be_running()

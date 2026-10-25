"""Per-prompt LLM routing: a classifier picks the provider and model per user turn.

``PromptRouter`` sits between the user context aggregator and the LLM switcher.
It holds each user turn's ``LLMContextFrame``, asks a ``PromptClassifier`` where
the prompt should go, has the switcher make that provider/model active, and
only then lets the frame through. It is a pass-through unless the user picked
AUTO as the language model.

Only downstream context frames are routed: those are new user turns. The
follow-up inference after a tool call (and the image-description trigger) is
pushed upstream by the assistant aggregator, never passes through here, and so
stays on the provider that issued the call.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from loguru import logger
from pipecat.frames.frames import Frame, LLMContextFrame, UserStartedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

if TYPE_CHECKING:
    from pipecat.processors.aggregators.llm_context import LLMContext

# Covers the embedding stage (~0.35 s) plus the LLM tiebreak (~2.7 s) on a Pi 5.
DEFAULT_CLASSIFY_TIMEOUT_SECS = 4.0


@dataclass(frozen=True)
class RoutingRequest:
    """What the classifier sees for one user turn."""

    # Text of the latest user message (image parts dropped; may be empty).
    text: str
    # The whole conversation. Read it, don't mutate it.
    context: LLMContext
    # Provider ids that are currently available to route to.
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class RoutingDecision:
    """Provider (Ubo service id, e.g. ``'anthropic'``) and model for one turn."""

    provider_id: str
    model: str
    # Appended to the composed system message for this turn (e.g. a domain
    # profile). Empty means the plain system message.
    system_addendum: str = ''


class PromptClassifier(Protocol):
    """Black box that picks where a prompt goes."""

    async def warm_up(self) -> None:
        """Load whatever ``classify`` needs; must not raise."""
        ...

    async def classify(self, request: RoutingRequest) -> RoutingDecision | None:
        """Return the target, or ``None`` to use the fallback provider."""
        ...


class AbstainingClassifier:
    """Placeholder classifier: never has an opinion, so AUTO uses its fallback."""

    async def warm_up(self) -> None:
        """Nothing to load."""

    async def classify(self, request: RoutingRequest) -> RoutingDecision | None:
        """Abstain."""
        _ = request
        return None


class RoutingTarget(Protocol):
    """The part of the LLM switcher the router drives."""

    @property
    def is_routing_enabled(self) -> bool:
        """Whether prompts should be routed at all."""
        ...

    def routing_candidates(self) -> tuple[str, ...]:
        """Return the provider ids the classifier may pick from."""
        ...

    async def route_to(
        self,
        decision: RoutingDecision | None,
        *,
        context: LLMContext,
    ) -> None:
        """Make the decided provider/model active for ``context``."""
        ...


def latest_user_text(context: LLMContext) -> str | None:
    """Return the text of the last message if it is a user message, else None."""
    messages = context.get_messages()
    if not messages:
        return None
    last = messages[-1]
    if not isinstance(last, dict) or last.get('role') != 'user':
        return None
    content = last.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(part['text'] for part in content if part['type'] == 'text')
    return None


class PromptRouter(FrameProcessor):
    """Route each user turn to the provider/model a classifier picks."""

    def __init__(
        self,
        *,
        target: RoutingTarget,
        classifier: PromptClassifier,
        timeout_secs: float = DEFAULT_CLASSIFY_TIMEOUT_SECS,
    ) -> None:
        """Initialize the router."""
        super().__init__()
        self._target = target
        self._classifier = classifier
        self._timeout_secs = timeout_secs
        self._warm_up_started = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Route user-turn context frames, pass everything else through.

        The held frame is dropped if the user barges in meanwhile: pipecat
        cancels this processor's task on an ``InterruptionFrame``.
        """
        await super().process_frame(frame, direction)
        if (
            isinstance(frame, UserStartedSpeakingFrame)
            and not self._warm_up_started
            and self._target.is_routing_enabled
        ):
            # Load the classifier's models while STT is still transcribing, so
            # the first routed turn doesn't pay the cold-load time.
            self._warm_up_started = True
            self.create_task(self._classifier.warm_up())
        if (
            direction == FrameDirection.DOWNSTREAM
            and isinstance(frame, LLMContextFrame)
            and self._target.is_routing_enabled
        ):
            text = latest_user_text(frame.context)
            if text is not None:
                await self._route(text, frame.context)
        await self.push_frame(frame, direction)

    async def _route(self, text: str, context: LLMContext) -> None:
        candidates = self._target.routing_candidates()
        logger.info(
            '[routing] router holding user turn for classification {extra}',
            extra={'text_chars': len(text), 'candidates': candidates},
        )
        start = time.perf_counter()
        decision = await self._classify(
            RoutingRequest(text=text, context=context, candidates=candidates),
        )
        classify_ms = round((time.perf_counter() - start) * 1000)
        if decision is None:
            logger.info(
                '[routing] router got no decision; using the fallback {extra}',
                extra={'classify_ms': classify_ms},
            )
        else:
            logger.info(
                '[routing] router got decision {extra}',
                extra={
                    'provider_id': decision.provider_id,
                    'model': decision.model,
                    'has_addendum': bool(decision.system_addendum),
                    'classify_ms': classify_ms,
                },
            )
        try:
            # Shielded: a barge-in may cancel the held prompt, but must not stop a
            # provider swap half-way through.
            await asyncio.shield(self._target.route_to(decision, context=context))
        except Exception:
            logger.exception('[routing] router: switching failed; using the active LLM')

    async def _classify(self, request: RoutingRequest) -> RoutingDecision | None:
        try:
            return await asyncio.wait_for(
                self._classifier.classify(request),
                timeout=self._timeout_secs,
            )
        except TimeoutError:
            logger.warning(
                '[routing] router: classifier timed out {extra}',
                extra={'timeout_secs': self._timeout_secs},
            )
        except Exception:
            logger.exception('[routing] router: classifier raised')
        return None

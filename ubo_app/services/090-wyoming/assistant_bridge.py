"""Correlation bridge between Wyoming requests and assistant pipeline frames."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

from constants import ASSISTANT_REQUEST_TIMEOUT_SECONDS

from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    REQUEST_PIPELINE_SOURCE_ID,
    AcceptableAssistanceFrame,
    AssistanceErrorFrame,
    AssistantCancelRequestAction,
    AssistantCompleteAction,
    AssistantHandleReportEvent,
    AssistantSynthesizeAction,
    AssistantTranscribeAction,
)

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions

AssistantRequestAction = (
    AssistantTranscribeAction | AssistantSynthesizeAction | AssistantCompleteAction
)
RequestFactory = Callable[[str], AssistantRequestAction]


class AssistantBridgeError(RuntimeError):
    """Assistant request failure that can be reported as a Wyoming response."""


class AssistantBridgeCancelledError(RuntimeError):
    """The Wyoming client disconnected before its assistant request completed."""


class AssistantBridge:
    """Route one-shot assistant frames to the request that owns their session."""

    def __init__(self) -> None:
        """Initialize the session-id to report-queue registry."""
        self._pending: dict[str, asyncio.Queue[AcceptableAssistanceFrame]] = {}
        self._overflowed: set[str] = set()

    def subscriptions(self) -> Subscriptions:
        """Return the single assistant-output subscription owned by this bridge."""
        return [store.subscribe_event(AssistantHandleReportEvent, self._on_report)]

    async def _on_report(self, event: AssistantHandleReportEvent) -> None:
        """Deliver a report only to its active request queue.

        Response streams must arrive whole. Dropping a frame to make room would
        silently delete audio from the middle of an utterance or text from the
        middle of an answer, and the request would still finish successfully, so
        an overflow fails the request instead.
        """
        if event.source_id != REQUEST_PIPELINE_SOURCE_ID:
            return
        queue = self._pending.get(event.data.session_id)
        if queue is None:
            return
        try:
            queue.put_nowait(event.data)
        except asyncio.QueueFull:
            self._overflowed.add(event.data.session_id)

    async def _next_frame(
        self,
        queue: asyncio.Queue[AcceptableAssistanceFrame],
        *,
        deadline: float,
        cancelled: asyncio.Event | None,
    ) -> AcceptableAssistanceFrame:
        """Await one frame, honoring the deadline and a client disconnect."""
        while True:
            if cancelled is not None and cancelled.is_set():
                raise AssistantBridgeCancelledError
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                msg = 'Assistant request timed out'
                raise AssistantBridgeError(msg)
            # Wake periodically while a disconnect is still possible so it is
            # noticed long before the full request deadline elapses.
            timeout = min(remaining, 0.25) if cancelled is not None else remaining
            try:
                return await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError as error:
                if cancelled is None:
                    msg = 'Assistant request timed out'
                    raise AssistantBridgeError(msg) from error

    async def request(
        self,
        action_factory: RequestFactory,
        *,
        cancelled: asyncio.Event | None = None,
    ) -> AsyncIterator[AcceptableAssistanceFrame]:
        """Dispatch a request and yield only its correlated terminal-frame stream."""
        session_id = uuid.uuid4().hex
        queue: asyncio.Queue[AcceptableAssistanceFrame] = asyncio.Queue(maxsize=64)
        self._pending[session_id] = queue
        store.dispatch(action_factory(session_id))
        deadline = asyncio.get_running_loop().time() + ASSISTANT_REQUEST_TIMEOUT_SECONDS
        completed = False
        try:
            while True:
                if session_id in self._overflowed:
                    msg = 'Assistant response outpaced the Wyoming client'
                    raise AssistantBridgeError(msg)
                frame = await self._next_frame(
                    queue,
                    deadline=deadline,
                    cancelled=cancelled,
                )
                if isinstance(frame, AssistanceErrorFrame):
                    raise AssistantBridgeError(frame.error)
                yield frame
                if frame.is_last_frame:
                    completed = True
                    return
        finally:
            self._pending.pop(session_id, None)
            self._overflowed.discard(session_id)
            if not completed:
                store.dispatch(AssistantCancelRequestAction(session_id=session_id))

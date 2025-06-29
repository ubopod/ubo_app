"""gRPC service that implements the Store service."""

from __future__ import annotations

from asyncio import Queue, QueueFull
from typing import TYPE_CHECKING, Any, cast

import betterproto
from ubo_app.logger import logger
from ubo_app.rpc.message_to_object import get_class, rebuild_object, reduce_group
from ubo_app.rpc.object_to_message import build_message
from ubo_app.store.main import UboAction, UboEvent, store

from ubo_bindings.store.v1 import (
    DispatchActionRequest,
    DispatchActionResponse,
    StoreServiceBase,
    SubscribeEventRequest,
    SubscribeEventResponse,
)
from ubo_bindings.ubo.v1 import Event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class StoreService(StoreServiceBase):
    """gRPC service class that implements the Store service."""

    async def dispatch_action(
        self: StoreService,
        dispatch_action_request: DispatchActionRequest,
    ) -> DispatchActionResponse:
        """Dispatch an action to the store."""
        if not dispatch_action_request.action:
            return DispatchActionResponse()
        try:
            action = rebuild_object(dispatch_action_request.action)
        except Exception:
            logger.exception(
                "Failed to build object from dispatch action request coming from gRPC",
                extra={
                    "request": dispatch_action_request,
                },
            )
        else:
            logger.debug(
                "Dispatching action coming from gRPC",
                extra={
                    "request": dispatch_action_request,
                    "action": action,
                },
            )
            store.dispatch(cast("UboAction", action))
        return DispatchActionResponse()

    async def subscribe_event(
        self: StoreService,
        subscribe_event_request: SubscribeEventRequest,
    ) -> AsyncIterator[SubscribeEventResponse]:
        """Subscribe to an event from the store."""
        logger.info(
            "Received event subscription over gRPC",
            extra={"request": subscribe_event_request},
        )
        event_class = get_class(reduce_group(subscribe_event_request.event))
        queue: Queue[UboEvent] = Queue(30)
        if event_class:

            def queue_event(event: UboEvent) -> None:
                """Put the event in the queue."""
                try:
                    queue.put_nowait(event)
                except QueueFull:
                    logger.verbose(
                        "Subscription event queue is full, dropping event",
                        extra={
                            "event": event,
                            "queue_size": queue.qsize(),
                        },
                    )

            store.subscribe_event(event_class, queue_event)
            while True:
                event = await queue.get()
                yield SubscribeEventResponse(
                    event=Event(
                        **{
                            betterproto.casing.snake_case(
                                type(event).__name__,
                            ): cast("Any", build_message(event)),
                        },
                    ),
                )

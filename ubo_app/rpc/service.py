"""gRPC service that implements the Store service."""

from __future__ import annotations

from asyncio import Queue
from typing import TYPE_CHECKING, Any, cast

import betterproto

from ubo_app.logging import logger
from ubo_app.rpc.generated.store.v1 import (
    DispatchActionRequest,
    DispatchActionResponse,
    StoreServiceBase,
    SubscribeEventRequest,
    SubscribeEventResponse,
)
from ubo_app.rpc.generated.ubo.v1 import Event
from ubo_app.rpc.message_to_object import get_class, rebuild_object, reduce_group
from ubo_app.rpc.object_to_message import build_message
from ubo_app.store.main import UboAction, UboEvent, store

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class StoreService(StoreServiceBase):
    """gRPC service class that implements the Store service."""

    async def dispatch_action(
        self: StoreService,
        dispatch_action_request: DispatchActionRequest,
    ) -> DispatchActionResponse:
        """Dispatch an action to the store."""
        logger.info(
            'Received action to be dispatched over gRPC',
            extra={
                'request': dispatch_action_request,
            },
        )
        if not dispatch_action_request.action:
            return DispatchActionResponse()
        try:
            action = rebuild_object(dispatch_action_request.action)
        except Exception:
            logger.exception('Failed to build object from dispatch action request')
        else:
            store.dispatch(cast(UboAction, action))
        return DispatchActionResponse()

    async def subscribe_event(
        self: StoreService,
        subscribe_event_request: SubscribeEventRequest,
    ) -> AsyncIterator[SubscribeEventResponse]:
        """Subscribe to an event from the store."""
        logger.info(
            'Received event subscription over gRPC',
            extra={'request': subscribe_event_request},
        )
        event_class = get_class(reduce_group(subscribe_event_request.event))
        queue: Queue[UboEvent] = Queue()
        if event_class:
            store.subscribe_event(
                event_class,
                lambda event: queue.put(event),
            )
            while True:
                event = await queue.get()
                yield SubscribeEventResponse(
                    event=Event(
                        **{
                            betterproto.casing.snake_case(
                                type(event).__name__,
                            ): cast(Any, build_message(event)),
                        },
                    ),
                )

"""gRPC service that implements the Store service."""

from __future__ import annotations

from typing import cast

from redux import BaseAction, BaseEvent

from ubo_app.logging import logger
from ubo_app.rpc.generated.store.v1 import (
    DispatchActionRequest,
    DispatchActionResponse,
    DispatchEventRequest,
    DispatchEventResponse,
    StoreServiceBase,
)
from ubo_app.rpc.message_to_object import rebuild_object
from ubo_app.store.main import store
from ubo_app.store.operations import UboAction, UboEvent


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
            action = rebuild_object(dispatch_action_request.action, BaseAction)
        except Exception:
            logger.exception('Failed to build object from dispatch action request')
        else:
            store.dispatch(cast(UboAction, action))
        return DispatchActionResponse()

    async def dispatch_event(
        self: StoreService,
        dispatch_event_request: DispatchEventRequest,
    ) -> DispatchEventResponse:
        """Dispatch an event to the store."""
        logger.info(
            'Received event to be dispatched over gRPC',
            extra={
                'request': dispatch_event_request,
            },
        )
        if not dispatch_event_request.event:
            return DispatchEventResponse()
        try:
            event = rebuild_object(dispatch_event_request.event, BaseEvent)
        except Exception:
            logger.exception('Failed to build object from dispatch event request')
        else:
            store.dispatch(cast(UboEvent, event))
        return DispatchEventResponse()

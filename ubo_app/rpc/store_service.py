"""gRPC service that implements the Store service."""

from __future__ import annotations

import ast
from asyncio import Queue, QueueFull
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

import betterproto
from betterproto.lib.std.google import protobuf as betterproto_protobuf
from ubo_app.logger import logger
from ubo_app.rpc.message_to_object import get_class, rebuild_object, reduce_group
from ubo_app.rpc.object_to_message import GRPCSerializable, build_message
from ubo_app.store.main import RootState, UboAction, UboEvent, store

from ubo_bindings.store.v1 import (
    DispatchActionRequest,
    DispatchActionResponse,
    StoreServiceBase,
    SubscribeEventRequest,
    SubscribeEventResponse,
    SubscribeStoreRequest,
    SubscribeStoreResponse,
)
from ubo_bindings.ubo.v1 import Event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable


def _is_valid_selector(selector: str) -> bool:
    try:
        n = ast.parse(selector, mode='eval').body
        while isinstance(n, (ast.Attribute, ast.Subscript)):
            if isinstance(n, ast.Attribute):
                n = n.value
            else:
                if not (
                    isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str)
                ):
                    return False
                n = n.value
        return isinstance(n, ast.Name) and n.id == 'state'
    except SyntaxError:
        return False


def _to_selector(selector: str) -> Callable[[RootState], Any]:
    if not _is_valid_selector(selector):
        msg = f'Invalid selector: {selector}'
        raise ValueError(msg)

    return eval(compile(f'lambda state: {selector}', '<string>', 'eval'))  # noqa: S307


def _pack_to_any(partial_state: GRPCSerializable) -> betterproto_protobuf.Any:
    """Convert a partial state to a betterproto.Message."""
    message = build_message(partial_state)

    if isinstance(message, str):
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.StringValue',
            value=betterproto_protobuf.StringValue(value=message).SerializeToString(),
        )
    if isinstance(message, bytes):
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.BytesValue',
            value=betterproto_protobuf.BytesValue(value=message).SerializeToString(),
        )
    if isinstance(message, bool):
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.BoolValue',
            value=betterproto_protobuf.BoolValue(value=message).SerializeToString(),
        )
    if isinstance(message, int):
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.Int64Value',
            value=betterproto_protobuf.Int64Value(value=message).SerializeToString(),
        )
    if isinstance(message, float):
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.DoubleValue',
            value=betterproto_protobuf.DoubleValue(value=message).SerializeToString(),
        )
    if message is None:
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.Empty',
            value=betterproto_protobuf.Empty().SerializeToString(),
        )
    if isinstance(message, Sequence):
        msg = 'Containers are not yet supported in the return type of a selector.'
        raise TypeError(msg)

    return betterproto_protobuf.Any(
        type_url=f'type.googleapis.com/ubo_bindings.ubo.v1.{type(message).__name__}',
        value=message.SerializeToString(),
    )


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
                'Failed to build object from dispatch action request coming from gRPC',
                extra={
                    'request': dispatch_action_request,
                },
            )
        else:
            logger.debug(
                'Dispatching action coming from gRPC',
                extra={
                    'request': dispatch_action_request,
                    'action': action,
                },
            )
            store.dispatch(cast('UboAction', action))
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
        queue: Queue[UboEvent] = Queue(30)
        if event_class:

            def queue_event(event: UboEvent) -> None:
                """Put the event in the queue."""
                try:
                    queue.put_nowait(event)
                except QueueFull:
                    logger.verbose(
                        'Subscription event queue is full, dropping event',
                        extra={
                            'event': event,
                            'queue_size': queue.qsize(),
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
                            ): cast('Any', build_message(event)),
                        },
                    ),
                )

    async def subscribe_store(
        self: StoreService,
        subscribe_store_request: SubscribeStoreRequest,
    ) -> AsyncIterator[SubscribeStoreResponse]:
        """Subscribe to the changes of selected parts of the store."""
        queue: Queue[Sequence[GRPCSerializable]] = Queue(30)

        selectors = [
            _to_selector(selector) for selector in subscribe_store_request.selectors
        ]

        def parent_selector(state: RootState) -> Sequence[GRPCSerializable]:
            return [selector(state) for selector in selectors]

        def queue_change(partial_state: Sequence[GRPCSerializable]) -> None:
            """Put the change in the queue."""
            try:
                queue.put_nowait(partial_state)
            except QueueFull:
                logger.verbose(
                    'Subscription store queue is full, dropping change',
                    extra={
                        'partial_state': partial_state,
                        'queue_size': queue.qsize(),
                    },
                )

        store.autorun(parent_selector)(queue_change)

        while True:
            change = await queue.get()
            yield SubscribeStoreResponse(
                results=[_pack_to_any(partial_state) for partial_state in change],
            )

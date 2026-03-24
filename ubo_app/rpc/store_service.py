"""gRPC service that implements the Store service."""

from __future__ import annotations

import ast
import contextlib
from asyncio import Queue, QueueFull, get_running_loop
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, cast

import betterproto
from betterproto.lib.std.google import protobuf as betterproto_protobuf
from ubo_app.logger import logger
from ubo_app.rpc.message_to_object import get_class, rebuild_object, reduce_group
from ubo_app.rpc.object_to_message import GRPCSerializable, build_message
from ubo_app.store.core.types import (
    StackChangedEvent as CoreStackChangedEvent,
)
from ubo_app.store.core.types import (
    ViewChangedEvent as CoreViewChangedEvent,
)
from ubo_app.store.main import RootState, UboAction, UboEvent, store
from ubo_app.utils.error_handlers import report_service_error

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
    # Short-circuit primitives before calling build_message() — avoids a
    # no-op round-trip through the full serialization machinery.
    if isinstance(partial_state, str):
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.StringValue',
            value=betterproto_protobuf.StringValue(
                value=partial_state,
            ).SerializeToString(),
        )
    if isinstance(partial_state, bytes):
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.BytesValue',
            value=betterproto_protobuf.BytesValue(
                value=partial_state,
            ).SerializeToString(),
        )
    if isinstance(partial_state, bool):
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.BoolValue',
            value=betterproto_protobuf.BoolValue(
                value=partial_state,
            ).SerializeToString(),
        )
    if isinstance(partial_state, int):
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.Int64Value',
            value=betterproto_protobuf.Int64Value(
                value=partial_state,
            ).SerializeToString(),
        )
    if isinstance(partial_state, float):
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.DoubleValue',
            value=betterproto_protobuf.DoubleValue(
                value=partial_state,
            ).SerializeToString(),
        )
    if partial_state is None:
        return betterproto_protobuf.Any(
            type_url='type.googleapis.com/google.protobuf.Empty',
            value=betterproto_protobuf.Empty().SerializeToString(),
        )

    message = build_message(partial_state)

    if isinstance(message, Sequence):
        msg = 'Containers are not yet supported in the return type of a selector.'
        raise TypeError(msg)

    if not isinstance(message, betterproto.Message):
        msg = f'Unexpected message type: {type(message)}'
        raise TypeError(msg)

    return betterproto_protobuf.Any(
        type_url=f'type.googleapis.com/ubo_bindings.ubo.v1.{type(message).__name__}',
        value=message.SerializeToString(),
    )


def _send_initial_state(
    event_class: type[UboEvent],
    queue_event: Callable[[UboEvent], None],
) -> None:
    """Send initial state for newly subscribed event types."""
    if event_class is CoreViewChangedEvent:

        @store.with_state(lambda state: state.main)
        def _send_initial_view(main: object) -> None:
            current_view = getattr(main, 'current_view', None)
            status_bar = getattr(main, 'status_bar', None)
            if current_view:
                queue_event(
                    CoreViewChangedEvent(
                        view=current_view,
                        status_bar=status_bar,
                    ),
                )

        _send_initial_view()

    if event_class is CoreStackChangedEvent:

        @store.with_state(lambda state: state.main.stack)
        def _send_initial_stack(
            stack: tuple[object, ...],
        ) -> None:
            if stack:
                queue_event(
                    CoreStackChangedEvent(stack=stack),  # type: ignore[arg-type]
                )

        _send_initial_stack()


class StoreService(StoreServiceBase):
    """gRPC service class that implements the Store service."""

    async def dispatch_action(
        self,
        dispatch_action_request: DispatchActionRequest,
    ) -> DispatchActionResponse:
        """Dispatch an action to the store."""
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
            logger.info(
                'Dispatching action coming from gRPC: %s',
                type(action).__name__,
            )
            store.dispatch(cast('UboAction', action))
            logger.info(
                'Dispatched action via gRPC completed: %s',
                type(action).__name__,
            )
        return DispatchActionResponse()

    async def subscribe_event(
        self,
        subscribe_event_request: SubscribeEventRequest,
    ) -> AsyncIterator[SubscribeEventResponse]:
        """Subscribe to an event from the store."""
        logger.info(
            'Received event subscription over gRPC',
            extra={'request': subscribe_event_request},
        )
        event_class = get_class(reduce_group(subscribe_event_request.event))
        queue: Queue[UboEvent] = Queue(30)
        loop = get_running_loop()
        if event_class:

            def queue_event(event: UboEvent) -> None:
                """Put the event in the queue (thread-safe)."""

                def _put() -> None:
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

                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(_put)

            # Pre-compute the snake_case event field name once per subscription
            event_field_name = betterproto.casing.snake_case(event_class.__name__)

            unsubscribe = store.subscribe_event(
                event_class,
                queue_event,
                keep_ref=False,
            )

            _send_initial_state(event_class, queue_event)

            try:
                while True:
                    event = await queue.get()
                    yield SubscribeEventResponse(
                        event=Event(
                            **{
                                event_field_name: cast(
                                    'Any', build_message(event),
                                ),
                            },
                        ),
                    )
            except Exception:
                logger.exception(
                    'Exception in event subscription',
                    extra={
                        'event_type': subscribe_event_request.event,
                    },
                )
                report_service_error()
            finally:
                logger.info(
                    'Unsubscribing from event subscription over gRPC',
                    extra={'request': subscribe_event_request},
                )
                unsubscribe()

    async def subscribe_store(
        self,
        subscribe_store_request: SubscribeStoreRequest,
    ) -> AsyncIterator[SubscribeStoreResponse]:
        """Subscribe to the changes of selected parts of the store."""
        queue: Queue[Sequence[GRPCSerializable]] = Queue(30)
        loop = get_running_loop()

        selectors = [
            _to_selector(selector) for selector in subscribe_store_request.selectors
        ]

        def parent_selector(state: RootState) -> Sequence[GRPCSerializable]:
            results: list[GRPCSerializable] = []
            for i, selector in enumerate(selectors):
                try:
                    results.append(selector(state))
                except AttributeError:
                    logger.warning(
                        'Selector %s raised AttributeError, returning None',
                        subscribe_store_request.selectors[i],
                        exc_info=True,
                    )
                    results.append(None)
            return tuple(results)

        logger.debug(
            'subscribe_store: setting up autorun for selectors: %s',
            subscribe_store_request.selectors,
        )

        @store.autorun(parent_selector)
        def queue_change(partial_state: Sequence[GRPCSerializable]) -> None:
            """Put the change in the queue (thread-safe)."""

            def _put() -> None:
                try:
                    queue.put_nowait(partial_state)
                except QueueFull:
                    logger.debug(
                        'Subscription store queue is full, dropping change',
                        extra={
                            'partial_state': partial_state,
                            'queue_size': queue.qsize(),
                        },
                    )

            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(_put)

        try:
            while True:
                change = await queue.get()
                yield SubscribeStoreResponse(
                    results=[_pack_to_any(partial_state) for partial_state in change],
                )
        except Exception:
            logger.exception(
                'Exception in store subscription',
                extra={
                    'selectors': subscribe_store_request.selectors,
                },
            )
            report_service_error()
        finally:
            queue_change.unsubscribe()

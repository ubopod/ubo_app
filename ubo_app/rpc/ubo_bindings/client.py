"""Async remote store client for dispatching operations to a gRPC server."""

from __future__ import annotations

from typing import TYPE_CHECKING, overload

from grpclib.client import Channel

from ubo_bindings.store.v1 import (
    DispatchActionRequest,
    DispatchEventRequest,
    StoreServiceStub,
    SubscribeEventRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_bindings.ubo.v1 import Action, Event


class AsyncRemoteStore:
    """Async remote store for dispatching operations to a gRPC server."""

    def __init__(self, host: str, port: int) -> None:
        """Initialize the async remote store."""
        self.channel = Channel(host=host, port=port)
        self.service = StoreServiceStub(self.channel)

    def close(self) -> None:
        """Close the channel."""
        self.channel.close()

    @overload
    async def dispatch_async(self, *, action: Action) -> None: ...
    @overload
    async def dispatch_async(self, *, event: Event) -> None: ...
    async def dispatch_async(
        self,
        *,
        action: Action | None = None,
        event: Event | None = None,
    ) -> None:
        """Dispatch an operation to the remote store."""
        if action is not None:
            await self.service.dispatch_action(DispatchActionRequest(action=action))
        if event is not None:
            await self.service.dispatch_event(DispatchEventRequest(event=event))

    async def subscribe_event(
        self,
        event_type: Event,
        callback: Callable[[Event], None],
    ) -> None:
        """Subscribe to the remote store."""
        async for response in self.service.subscribe_event(
            SubscribeEventRequest(event=event_type),
        ):
            callback(response.event)

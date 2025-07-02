"""Async remote store client for dispatching operations to a gRPC server."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, overload

from grpclib.client import Channel

from ubo_bindings.secrets.v1 import QuerySecretRequest, SecretsServiceStub
from ubo_bindings.store.v1 import (
    DispatchActionRequest,
    DispatchEventRequest,
    StoreServiceStub,
    SubscribeEventRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_bindings.ubo.v1 import Action, Event


class UboRPCClient:
    """Async remote store for dispatching operations to a gRPC server."""

    def __init__(self, host: str, port: int) -> None:
        """Initialize the async remote store."""
        self.event_loop = asyncio.get_event_loop()
        self.channel = Channel(host=host, port=port, loop=self.event_loop)
        self.store_service = StoreServiceStub(self.channel)
        self.secrets_service = SecretsServiceStub(self.channel)

    def close(self) -> None:
        """Close the channel."""
        self.channel.close()

    @overload
    def dispatch(self, *, action: Action) -> None: ...
    @overload
    def dispatch(self, *, event: Event) -> None: ...
    def dispatch(
        self,
        *,
        action: Action | None = None,
        event: Event | None = None,
    ) -> None:
        """Dispatch an operation to the remote store."""
        if action is not None:
            self.event_loop.create_task(
                self.store_service.dispatch_action(
                    DispatchActionRequest(action=action)
                ),
            )
        if event is not None:
            self.event_loop.create_task(
                self.store_service.dispatch_event(DispatchEventRequest(event=event)),
            )

    def subscribe_event(
        self,
        event_type: Event,
        callback: Callable[[Event], None],
    ) -> None:
        """Subscribe to the remote store."""

        async def iterator():
            async for response in self.store_service.subscribe_event(
                SubscribeEventRequest(event=event_type),
            ):
                callback(response.event)

        self.event_loop.create_task(iterator())

    async def query_secret(
        self,
        key: str,
        *,
        covered: bool = False,
        default: str | None = None,
    ) -> str | None:
        """Query a secret from the secrets manager."""
        result = await self.secrets_service.query_secret(
            QuerySecretRequest(key=key, covered=covered),
        )

        match result.error:
            case "Secret not found":
                return default
            case None:
                return result.value
            case _:
                raise RuntimeError(f"Error querying secret: {result.error}")

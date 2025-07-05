"""Async remote store client for dispatching operations to a gRPC server."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast, overload

from betterproto.lib.std.google import protobuf as betterproto_protobuf
from grpclib.client import Channel

import ubo_bindings.ubo.v1
from ubo_bindings.secrets.v1 import QuerySecretRequest, SecretsServiceStub
from ubo_bindings.store.v1 import (
    DispatchActionRequest,
    DispatchEventRequest,
    StoreServiceStub,
    SubscribeEventRequest,
    SubscribeStoreRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from betterproto import Message

    from ubo_bindings.ubo.v1 import Action, Event


def _unpack_from_any(message: betterproto_protobuf.Any) -> Message:
    if not message.type_url.startswith('type.googleapis.com/'):
        msg = f'Unsupported type URL: {message.type_url}'
        raise ValueError(msg)

    type_name = message.type_url[len('type.googleapis.com/') :]

    if type_name.startswith('google.protobuf.'):
        type_name = type_name[len('google.protobuf.') :]
        cls = cast('type[Message]', getattr(betterproto_protobuf, type_name, None))
        if cls is not None:
            return cls.FromString(message.value)

    if type_name.startswith('ubo_bindings.ubo.v1.'):
        type_name = type_name[len('ubo_bindings.ubo.v1.') :]
        cls = cast('type[Message]', getattr(ubo_bindings.ubo.v1, type_name, None))
        if cls is not None:
            return cls.FromString(message.value)

    msg = f'Unknown type URL: {message.type_url}'
    raise ValueError(msg)


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
                    DispatchActionRequest(action=action),
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
    ) -> Callable[[], None]:
        """Subscribe to the remote store."""

        async def iterator() -> None:
            async for response in self.store_service.subscribe_event(
                SubscribeEventRequest(event=event_type),
            ):
                callback(response.event)

        task = self.event_loop.create_task(iterator())

        def unsubscribe() -> None:
            task.cancel()

        return unsubscribe

    def autorun(
        self,
        selectors: list[str],
    ) -> Callable[[Callable[[list], None]], Callable[[], None]]:
        """Autorun a function based on store changes."""

        def wrapper(callback: Callable[[list], None]) -> Callable[[], None]:
            async def iterator() -> None:
                async for response in self.store_service.subscribe_store(
                    SubscribeStoreRequest(selectors=selectors),
                ):
                    callback([_unpack_from_any(item) for item in response.results])

            task = self.event_loop.create_task(iterator())

            def unsubscribe() -> None:
                task.cancel()

            return unsubscribe

        return wrapper

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
            case 'Secret not found':
                return default
            case None:
                if result.value is None:
                    msg = 'Secret value is None and there is no error.'
                    raise RuntimeError(msg)
                return result.value
            case _:
                msg = f'Error querying secret: {result.error}'
                raise RuntimeError(msg)

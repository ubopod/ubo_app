"""Client for the remote store."""

from __future__ import annotations

from typing import TYPE_CHECKING, overload

from grpclib.client import Channel

from ubo_app.rpc.generated.store.v1 import (
    DispatchActionRequest,
    DispatchEventRequest,
    StoreServiceStub,
    SubscribeEventRequest,
)
from ubo_app.rpc.generated.ubo.v1 import (
    Action,
    Event,
    Key,
    KeypadKeyPressAction,
    Notification,
    NotificationActions,
    NotificationActionsItem,
    NotificationDispatchItem,
    NotificationDispatchItemOperation,
    NotificationsAddAction,
)

if TYPE_CHECKING:
    from collections.abc import Callable

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 50051


class AsyncRemoteStore:
    """Async remote store for dispatching operations to a gRPC server."""

    def __init__(
        self: AsyncRemoteStore,
        host: str,
        port: int,
    ) -> None:
        """Initialize the async remote store."""
        self.channel = Channel(host=host, port=port)
        self.service = StoreServiceStub(self.channel)

    @overload
    async def dispatch_async(
        self: AsyncRemoteStore,
        *,
        action: Action,
    ) -> None: ...
    @overload
    async def dispatch_async(
        self: AsyncRemoteStore,
        *,
        event: Event,
    ) -> None: ...
    async def dispatch_async(
        self: AsyncRemoteStore,
        *,
        action: Action | None = None,
        event: Event | None = None,
    ) -> None:
        """Dispatch an operation to the remote store."""
        return
        """Dispatch an operation to the remote store."""
        if action is not None:
            await self.service.dispatch_action(DispatchActionRequest(action=action))
        if event is not None:
            await self.service.dispatch_event(DispatchEventRequest(event=event))

    async def subscribe_event(
        self: AsyncRemoteStore,
        event_type: Event,
        callback: Callable[[Event], None],
    ) -> None:
        """Subscribe to the remote store."""
        async for response in self.service.subscribe_event(
            SubscribeEventRequest(event=event_type),
        ):
            callback(response.event)


async def connect() -> None:
    """Connect to the gRPC server."""
    store = AsyncRemoteStore(SERVER_HOST, SERVER_PORT)
    await store.dispatch_async(
        action=Action(
            keypad_key_press_action=KeypadKeyPressAction(
                key=Key.L1,
                time=0.0,
            ),
        ),
    )
    await store.dispatch_async(
        action=Action(
            notifications_add_action=NotificationsAddAction(
                notification=Notification(
                    title='Hello',
                    content='World',
                    actions=NotificationActions(
                        items=[
                            NotificationActionsItem(
                                notification_dispatch_item=NotificationDispatchItem(
                                    label='custom action',
                                    color='#ff0000',
                                    background_color='#00ff00',
                                    icon='󰑣',
                                    operation=NotificationDispatchItemOperation(
                                        ubo_action=Action(
                                            keypad_key_press_action=KeypadKeyPressAction(
                                                key=Key.L1,
                                                time=0.0,
                                            ),
                                        ),
                                    ),
                                ),
                            ),
                        ],
                    ),
                ),
            ),
        ),
    )
    store.channel.close()


if __name__ == '__main__':
    import asyncio

    asyncio.run(connect())

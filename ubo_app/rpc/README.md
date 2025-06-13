# Ubo App Python Bindings

This repository contains Python bindings for the Ubo App, allowing developers to interact with the Ubo App's functionality using Python over gRPC.

## Sample Usage

```python
import asyncio

from ubo_bindings.client import AsyncRemoteStore
from ubo_bindings.ubo.v1 import Action, Notification, NotificationsAddAction

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


async def main():
    client = AsyncRemoteStore("localhost", 50051)

    action = Action(
        notifications_add_action=NotificationsAddAction(
            notification=Notification(
                title="Test Notification",
                content="This is a test notification.",
            ),
        ),
    )

    await client.dispatch_async(action=action)
    client.channel.close()


loop.run_until_complete(main())
```

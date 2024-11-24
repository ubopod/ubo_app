"""Utilities for logging the output of failed processes."""

from asyncio.subprocess import Process

from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationExtraInformation,
    NotificationsAddAction,
)


async def log_async_process(process: Process) -> None:
    """Log the output of the process if it fails.

    Arguments:
    ---------
    process: Process - The process to log the output of.

    """
    if process.returncode != 0:
        logs = ''
        if process.stdout:
            logs += 'stdout:\n' + (await process.stdout.read()).decode()
        if process.stderr:
            logs += 'stderr:\n' + (await process.stderr.read()).decode()
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Docker Composition Error',
                    content='Failed to run the composition',
                    extra_information=NotificationExtraInformation(
                        text=logs,
                    ),
                    importance=Importance.HIGH,
                ),
            ),
        )

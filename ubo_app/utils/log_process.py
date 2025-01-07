"""Utilities for logging the output of failed processes."""

from asyncio.subprocess import Process

from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationsAddAction,
)
from ubo_app.store.services.voice import ReadableInformation


async def log_async_process(
    process: Process,
    *,
    title: str = 'Error',
    message: str,
) -> None:
    """Log the output of the process if it fails.

    Arguments:
    ---------
    process: Process - The process to log the output of.
    title: str - The title of the notification.
    message: str - The message to display in the notification.

    """
    if process.returncode != 0:
        logs = ''
        if process.stdout:
            logs += '---\nstdout:\n' + (await process.stdout.read()).decode()
        if process.stderr:
            logs += '---\nstderr:\n' + (await process.stderr.read()).decode()
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title=title,
                    content=message,
                    extra_information=ReadableInformation(
                        text=logs,
                    ),
                    importance=Importance.HIGH,
                ),
            ),
        )

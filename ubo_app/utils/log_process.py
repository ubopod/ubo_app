"""Utilities for logging the output of failed processes."""

from asyncio.subprocess import Process

from redux import DispatchParameters

from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils.error_handlers import report_service_error


async def log_async_process(
    process: Process,
    *,
    title: str = 'Error',
    message: str,
) -> DispatchParameters:
    """Log the output of the process if it fails.

    Arguments:
    ---------
    process: Process - The process to log the output of.
    title: str - The title of the notification.
    message: str - The message to display in the notification.

    """
    if process.returncode != 0:
        logs = '\n'
        if process.stdout:
            logs += '------\nstdout:\n' + (await process.stdout.read()).decode()
        if process.stderr:
            logs += '------\nstderr:\n' + (await process.stderr.read()).decode()
        report_service_error(context={'message': logs})
        return (
            NotificationsAddAction(
                notification=Notification(
                    title=title,
                    content=message,
                    extra_information=ReadableInformation(
                        text=logs,
                        piper_text='',
                        picovoice_text='',
                    ),
                    importance=Importance.HIGH,
                ),
            ),
        )

    return []

# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import asyncio
import sys
import threading
import time
import traceback
import weakref
from typing import TYPE_CHECKING, cast

from ubo_app.utils.eeprom import read_serial_number

if TYPE_CHECKING:
    from types import TracebackType


def setup_sentry() -> None:  # pragma: no cover
    import os

    import sentry_sdk

    serial_number = read_serial_number()

    if 'SENTRY_DSN' in os.environ:
        from sentry_sdk import set_user

        sentry_sdk.init(
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
            ignore_errors=[KeyboardInterrupt, asyncio.CancelledError],
            server_name=serial_number,
        )
        set_user({'id': serial_number})


def get_all_thread_stacks() -> dict[str, list[str]]:
    id_to_name = {th.ident: th.name for th in threading.enumerate()}
    thread_stacks = {}
    for thread_id, frame in sys._current_frames().items():  # noqa: SLF001
        thread_stacks[id_to_name.get(thread_id, f'unknown-{thread_id}')] = (
            traceback.format_stack(frame)
        )
    return thread_stacks


def get_all_thread_stacks_string() -> str:
    result = ''
    for thread_name, stack in get_all_thread_stacks().items():
        result += thread_name + '\n'
        result += '-----\n'
        result += '\n'.join(stack) + '\n'
        result += '-' * 70 + '\n'
    return result


def global_exception_handler(
    exception_type: type[BaseException],
    exception_value: BaseException,
    exception_traceback: TracebackType,
) -> None:
    _ = exception_type, exception_traceback
    from ubo_app.logger import logger

    threads_info = get_all_thread_stacks()

    logger.exception(
        'Global exception',
        exc_info=exception_value,
    )
    logger.verbose(
        'Global exception',
        extra={
            'threads': threads_info,
        },
        exc_info=exception_value,
    )


def thread_exception_handler(args: threading.ExceptHookArgs) -> None:
    from ubo_app.logger import logger

    threads_info = get_all_thread_stacks()

    _, exception_value, _, thread = args
    label = getattr(thread, 'label', None)
    service_id = getattr(thread, 'service_id', None)
    service_path = getattr(thread, 'path', None)

    logger.exception(
        'Thread exception',
        extra={
            'exception_thread': thread,
            'service': label,
            **(
                {
                    'service_id': service_id,
                }
                if service_id
                else {'service_path': service_path}
            ),
        },
        exc_info=exception_value,
    )
    logger.verbose(
        'Thread exception',
        extra={
            'exception_thread': thread,
            'threads': threads_info,
            'service': label,
            **(
                {
                    'service_id': service_id,
                }
                if service_id
                else {'service_path': service_path}
            ),
        },
        exc_info=exception_value,
    )


STACKS = weakref.WeakKeyDictionary(dict[asyncio.Task, str]())


def loop_exception_handler(
    loop: asyncio.AbstractEventLoop,
    context: dict[str, object],
) -> None:
    from ubo_app.constants import DEBUG_TASKS
    from ubo_app.logger import logger

    threads_info = get_all_thread_stacks()

    exception = context.get('exception')

    if DEBUG_TASKS:
        task = cast('asyncio.Task', context.get('future') or context.get('task'))
        parent_stack = STACKS.get(task, '<unavailable>') if task else '<unavailable>'
    else:
        parent_stack = None

    thread = threading.current_thread()
    label = getattr(thread, 'label', None)
    service_id = getattr(thread, 'service_id', None)
    service_path = getattr(thread, 'path', None)

    if exception:
        if not isinstance(exception, asyncio.CancelledError):
            logger.exception(
                'Event loop exception',
                extra={
                    'service': label,
                    **(
                        {
                            'service_id': service_id,
                        }
                        if service_id
                        else {'service_path': service_path}
                    ),
                    'loop': loop,
                    'error_message': context.get('message'),
                    'future': context.get('future'),
                    'parent_stack': parent_stack,
                },
                exc_info=cast('Exception', exception),
            )
        logger.verbose(
            'Event loop exception',
            extra={
                'service': label,
                **(
                    {
                        'service_id': service_id,
                    }
                    if service_id
                    else {'service_path': service_path}
                ),
                'loop': loop,
                'error_message': context.get('message'),
                'future': context.get('future'),
                'threads': threads_info,
                'parent_stack': parent_stack,
            },
            exc_info=cast('Exception', exception),
        )
    else:
        logger.error(
            'Event loop exception handler called without an exception in the context',
            extra={
                'service': label,
                **(
                    {
                        'service_id': service_id,
                    }
                    if service_id
                    else {'service_path': service_path}
                ),
                'loop': loop,
                'context': context,
                'parent_stack': parent_stack,
            },
        )

    if service_id is not None:
        report_service_error(
            service_id=service_id,
            exception=exception,
            context=context,
        )


def report_service_error(
    *,
    service_id: str | None = None,
    exception: object | None = None,
    context: dict[str, object] | None = None,
) -> None:
    context = context or {}

    if service_id is None:
        from ubo_app.utils.service import get_service

        service_id = get_service().service_id

    if exception is None:
        _, exception, _ = sys.exc_info()

    from ubo_app.store.settings.types import (
        ErrorReport,
        SettingsReportServiceErrorAction,
    )

    message = ''

    if isinstance(exception, Exception):
        message += '[b]exception:[/b] ' + ''.join(
            traceback.format_exception(
                type(exception),
                exception,
                exception.__traceback__,
            ),
        )

    for key in context:
        message += f'\n\n[b]{key}:[/b] {context.get(key)}'

    try:
        from ubo_app.store.main import store

    except RuntimeError as exception_:
        if exception_.args[0] != 'Store should be created in the main thread':
            raise
    else:
        store.dispatch(
            SettingsReportServiceErrorAction(
                service_id=service_id,
                error=ErrorReport(
                    message=message,
                    timestamp=time.time(),
                ),
            ),
        )


def setup_error_handling() -> None:
    setup_sentry()
    threading.excepthook = thread_exception_handler
    sys.excepthook = global_exception_handler

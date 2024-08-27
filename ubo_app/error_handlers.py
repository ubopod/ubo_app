# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import asyncio
import sys
import threading
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


def global_exception_handler(
    exception_type: type[BaseException],
    exception_value: BaseException,
    exception_traceback: TracebackType,
) -> None:
    _ = exception_type, exception_traceback
    from ubo_app.logging import logger

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
    from ubo_app.logging import logger

    threads_info = get_all_thread_stacks()

    _, exception_value, _, thread = args

    logger.exception(
        'Thread exception',
        extra={
            'exception_thread': thread,
        },
        exc_info=exception_value,
    )
    logger.verbose(
        'Thread exception',
        extra={
            'exception_thread': thread,
            'threads': threads_info,
        },
        exc_info=exception_value,
    )


STACKS = weakref.WeakKeyDictionary(dict[asyncio.Task, str]())


def loop_exception_handler(
    loop: asyncio.AbstractEventLoop,
    context: dict[str, object],
) -> None:
    from ubo_app.constants import DEBUG_MODE_TASKS
    from ubo_app.logging import logger

    threads_info = get_all_thread_stacks()

    exception = context.get('exception')

    if DEBUG_MODE_TASKS:
        task = cast(asyncio.Task, context.get('future') or context.get('task'))
        parent_stack = STACKS.get(task, '<unavailable>') if task else '<unavailable>'
    else:
        parent_stack = None

    if exception and not isinstance(exception, asyncio.CancelledError):
        logger.exception(
            'Event loop exception',
            extra={
                'loop': loop,
                'error_message': context.get('message'),
                'future': context.get('future'),
                'parent_stack': parent_stack,
            },
            exc_info=cast(Exception, exception),
        )
        logger.verbose(
            'Event loop exception',
            extra={
                'loop': loop,
                'error_message': context.get('message'),
                'future': context.get('future'),
                'threads': threads_info,
                'parent_stack': parent_stack,
            },
            exc_info=cast(Exception, exception),
        )
    else:
        logger.error(
            'Event loop exception handler called without an exception in the context',
            extra={
                'loop': loop,
                'context': context,
                'parent_stack': parent_stack,
            },
        )


def setup_error_handling() -> None:
    setup_sentry()
    threading.excepthook = thread_exception_handler
    sys.excepthook = global_exception_handler

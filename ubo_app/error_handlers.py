# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import sys
import threading
import traceback
from typing import TYPE_CHECKING

import sentry_sdk

if TYPE_CHECKING:
    from types import TracebackType


def setup_sentry() -> None:  # pragma: no cover
    from ubo_app.constants import SENTRY_DSN

    if SENTRY_DSN:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
        )


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
    from ubo_app.logging import logger

    error_message = ''.join(
        traceback.format_exception(
            exception_type,
            exception_value,
            exception_traceback,
        ),
    )
    threads_info = get_all_thread_stacks()

    logger.error(
        f"""Uncaught exception: {exception_type}: {exception_value}
{error_message}""",
    )
    logger.debug(
        f"""Uncaught exception: {exception_type}: {exception_value}
{error_message}""",
        extra={'threads': threads_info},
    )


def thread_exception_handler(args: threading.ExceptHookArgs) -> None:
    from ubo_app.logging import logger

    error_message = ''.join(
        traceback.format_exception(*args[:3]),
    )
    threads_info = get_all_thread_stacks()

    exception_type, exception_value, _, thread = args

    logger.error(
        f"""Uncaught exception in thread {thread}: {exception_type}: {exception_value}
{error_message}""",
    )
    logger.debug(
        f"""Uncaught exception in thread {thread}: {exception_type}: {exception_value}
{error_message}""",
        extra={'threads': threads_info, 'thread': thread},
    )


def setup_error_handling() -> None:
    setup_sentry()
    threading.excepthook = thread_exception_handler
    sys.excepthook = global_exception_handler

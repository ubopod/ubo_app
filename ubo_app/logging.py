# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import atexit
import json
import logging
import logging.handlers
import sys
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

VERBOSE = 5


def handle_circular_references(obj: object, seen: set[int] | None = None) -> object:
    if seen is None:
        seen = set()

    obj_id = id(obj)
    if obj_id in seen:
        return None

    seen.add(obj_id)

    if isinstance(obj, dict):
        return {
            key: handle_circular_references(value, seen) for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [handle_circular_references(item, seen) for item in obj]
    if isinstance(obj, tuple):
        return tuple(handle_circular_references(item, seen) for item in obj)
    return str(obj)


class UboLogger(logging.getLoggerClass()):
    def __init__(self: UboLogger, name: str, level: int = logging.NOTSET) -> None:
        super().__init__(name, level)

        logging.addLevelName(VERBOSE, 'VERBOSE')

    def verbose(
        self: UboLogger,
        msg: object,
        *args: tuple[object],
        exc_info: logging._ExcInfoType | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        if self.isEnabledFor(VERBOSE):
            self._log(
                VERBOSE,
                msg,
                args=args,
                exc_info=exc_info,
                stack_info=stack_info,
                stacklevel=stacklevel,
                extra=extra,
            )


logging.setLoggerClass(UboLogger)


def get_logger(name: str) -> UboLogger:
    return cast(UboLogger, logging.getLogger(name))


logger = get_logger('ubo-app')
logger.propagate = False


class ExtraFormatter(logging.Formatter):
    def_keys = (
        'name',
        'msg',
        'args',
        'levelname',
        'levelno',
        'pathname',
        'filename',
        'module',
        'exc_info',
        'exc_text',
        'stack_info',
        'lineno',
        'funcName',
        'created',
        'msecs',
        'relativeCreated',
        'thread',
        'threadName',
        'processName',
        'process',
        'message',
    )

    def format(self: ExtraFormatter, record: logging.LogRecord) -> str:
        string = super().format(record)
        extra = {k: v for k, v in record.__dict__.items() if k not in self.def_keys}
        if len(extra) > 0:
            string += ' - extra: ' + json.dumps(
                handle_circular_references(extra),
                sort_keys=True,
                indent=2,
                default=str,
            ).replace('\\n', '\n')

        return string


def add_stdout_handler(logger: UboLogger, level: int = logging.DEBUG) -> None:
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(
        ExtraFormatter(
            '%(created)f [%(levelname)s] %(message)s',
            '%Y-%m-%d %H:%M:%S',
        ),
    )
    logger.addHandler(stdout_handler)

    atexit.register(stdout_handler.flush)


def add_file_handler(logger: UboLogger, level: int = logging.DEBUG) -> None:
    file_handler = logging.handlers.RotatingFileHandler(
        f'{logger.name}.log',
        backupCount=3,
    )
    file_handler.doRollover()
    file_handler.setLevel(level)
    file_handler.setFormatter(
        ExtraFormatter(
            '%(created)f [%(levelname)s] %(message)s',
            '%Y-%m-%d %H:%M:%S',
        ),
    )
    logger.addHandler(file_handler)

    atexit.register(file_handler.flush)


def setup_logging() -> None:
    from ubo_app.constants import GUI_LOG_LEVEL, LOG_LEVEL

    if LOG_LEVEL:
        import logging

        level = globals().get(
            LOG_LEVEL,
            getattr(logging, LOG_LEVEL, logging.INFO),
        )

        logger.setLevel(level)
        add_file_handler(logger, level)
        add_stdout_handler(logger, level)

    if GUI_LOG_LEVEL:
        import logging

        import ubo_gui.logger

        level = getattr(
            ubo_gui.logger,
            GUI_LOG_LEVEL,
            getattr(logging, GUI_LOG_LEVEL, logging.INFO),
        )

        ubo_gui.logger.logger.setLevel(level)
        ubo_gui.logger.add_file_handler(level)
        ubo_gui.logger.add_stdout_handler(level)


__all__ = ('logger', 'add_stdout_handler', 'add_file_handler', 'setup_logging')

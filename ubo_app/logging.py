# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import atexit
import logging
import sys
from typing import Mapping, cast

from ubo_app.constants import DEBUG_MODE

VERBOSE = 5


class UboLogger(logging.getLoggerClass()):
    def __init__(self: UboLogger, name: str, level: int = logging.NOTSET) -> None:
        super().__init__(name, level)

        logging.addLevelName(VERBOSE, 'VERBOSE')

    def verbose(  # noqa: PLR0913
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
                *args,
                exc_info=exc_info,
                stack_info=stack_info,
                stacklevel=stacklevel,
                extra=extra,
            )


logging.setLoggerClass(UboLogger)

logger = cast(UboLogger, logging.getLogger('ubo-app'))
if DEBUG_MODE:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)
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

    def format(self: ExtraFormatter, record: logging.LogRecord) -> str:  # noqa: A003
        string = super().format(record)
        extra = {k: v for k, v in record.__dict__.items() if k not in self.def_keys}
        if len(extra) > 0:
            string += ' - extra: ' + str(extra)

        return string


def add_stdout_handler() -> None:
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.setFormatter(
        ExtraFormatter(
            '%(created)f [%(levelname)s] %(message)s',
            '%Y-%m-%d %H:%M:%S',
        ),
    )
    logger.addHandler(stdout_handler)

    atexit.register(stdout_handler.flush)


def add_file_handler() -> None:
    file_handler = logging.FileHandler('ubo-app.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        ExtraFormatter(
            '%(created)f [%(levelname)s] %(message)s',
            '%Y-%m-%d %H:%M:%S',
        ),
    )
    logger.addHandler(file_handler)

    atexit.register(file_handler.flush)


__all__ = ('logger', 'add_stdout_handler', 'add_file_handler')

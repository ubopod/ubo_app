# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from typing import TYPE_CHECKING, ClassVar, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ubo_app.utils.types import Subscriptions

VERBOSE = 5


COLORS_HEX = {
    logging.NOTSET: '#545454',  # Very Dark Gray
    VERBOSE: '#848484',  # Dark Gray
    logging.DEBUG: '#b6b6b6',  # Light Gray
    logging.INFO: '#64C864',  # Green
    logging.WARNING: '#FFA500',  # Orange
    logging.ERROR: '#FF9696',  # Red
    logging.CRITICAL: '#FF00FF',  # Magenta
}
COLORS_ANSI_RGB = {
    logging.NOTSET: '\033[38;2;84;84;84m',  # Very Dark Gray (RGB)
    VERBOSE: '\033[38;2;132;132;132m',  # Dark Gray (RGB)
    logging.DEBUG: '\033[38;2;182;182;182m',  # Light Gray (RGB)
    logging.INFO: '\033[38;2;100;200;100m',  # Green (RGB)
    logging.WARNING: '\033[38;2;255;165;0m',  # Orange (RGB)
    logging.ERROR: '\033[38;2;255;150;150m',  # Red (RGB)
    logging.CRITICAL: '\033[38;2;255;0;255m',  # Magenta (RGB)
}
COLORS_ANSI_BASIC = {
    logging.NOTSET: '\033[90m',  # Very Dark Gray (ANSI)
    VERBOSE: '\033[37m',  # Dark Gray (ANSI)
    logging.DEBUG: '\033[97m',  # Light Gray (ANSI)
    logging.INFO: '\033[92m',  # Green (ANSI)
    logging.WARNING: '\033[93m',  # Yellow (ANSI)
    logging.ERROR: '\033[91m',  # Red (ANSI)
    logging.CRITICAL: '\033[95m',  # Magenta (ANSI)
}
ANSI_RESET = '\033[0m'  # Reset color


def handle_circular_references(
    obj: object,
    seen: dict[int, str | dict | list | tuple] | None = None,
) -> object:
    if seen is None:
        seen = {}

    obj_id = id(obj)
    if obj_id in seen:
        return None

    seen[obj_id] = '<circular reference>'

    if isinstance(obj, dict):
        result = {
            key: handle_circular_references(value, seen) for key, value in obj.items()
        }
    elif isinstance(obj, list):
        result = [handle_circular_references(item, seen) for item in obj]
    elif isinstance(obj, tuple):
        result = tuple(handle_circular_references(item, seen) for item in obj)
    else:
        result = str(obj)

    seen[obj_id] = result
    return result


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
    logger = cast('UboLogger', logging.getLogger(name))
    logger.propagate = False
    return logger


def supports_truecolor() -> bool:
    """Check if the terminal supports truecolor (24-bit)."""
    color_term = os.environ.get('COLORTERM', '')
    return color_term == 'truecolor'


logger = get_logger('ubo-app')


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
            string += ' - ' + json.dumps(
                handle_circular_references(extra),
                sort_keys=True,
                indent=2,
                default=str,
            ).replace('\\n', '\n')

        return string


class StdOutExtraFormatter(ExtraFormatter):
    max_length: int | None = None

    def format(self: StdOutExtraFormatter, record: logging.LogRecord) -> str:
        string = super().format(record)

        if self.max_length and len(string) > self.max_length:
            string = string[: self.max_length - 3] + '...'

        # Get the color for the log level and apply it
        color = (COLORS_ANSI_RGB if supports_truecolor() else COLORS_ANSI_BASIC).get(
            record.levelno,
            ANSI_RESET,
        )
        return f'{color}{string}{ANSI_RESET}'


class ThreadLevelFilter(logging.Filter):
    thread_levels: ClassVar[dict[str, int]] = {}

    @classmethod
    def set_thread_level(cls, thread_name: str, level: int | None) -> None:
        if level is None:
            if thread_name in cls.thread_levels:
                del cls.thread_levels[thread_name]
        else:
            cls.thread_levels[thread_name] = level

    def filter(self: ThreadLevelFilter, record: logging.LogRecord) -> bool:
        thread_name = record.threadName
        if thread_name is None:
            return True
        level = self.thread_levels.get(thread_name, logging.NOTSET)
        return record.levelno >= level


thread_level_filter = ThreadLevelFilter()


def add_stdout_handler(
    logger: UboLogger,
    level: int = logging.DEBUG,
) -> Subscriptions:
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    formatter = StdOutExtraFormatter(
        '%(created)f [%(levelname)s] %(message)s',
        '%Y-%m-%d %H:%M:%S',
    )
    if level <= logging.DEBUG:
        formatter.max_length = 10000
    stdout_handler.setFormatter(formatter)
    stdout_handler.addFilter(thread_level_filter)
    logger.addHandler(stdout_handler)

    def cleanup() -> None:
        stdout_handler.flush()
        stdout_handler.close()
        logger.removeHandler(stdout_handler)

    return [cleanup]


def add_file_handler(
    logger: UboLogger,
    level: int = logging.DEBUG,
) -> Subscriptions:
    file_handler = logging.handlers.RotatingFileHandler(
        f'{logger.name}.log',
        backupCount=3,
        maxBytes=1_000_000,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(
        ExtraFormatter(
            '%(created)f [%(levelname)s] %(message)s',
            '%Y-%m-%d %H:%M:%S',
        ),
    )
    file_handler.addFilter(thread_level_filter)
    logger.addHandler(file_handler)

    def cleanup() -> None:
        file_handler.flush()
        file_handler.close()
        logger.removeHandler(file_handler)

    return [cleanup]


def get_log_level() -> int | None:
    from ubo_app.constants import LOG_LEVEL

    if LOG_LEVEL:
        import logging

        return logging.getLevelNamesMapping()[LOG_LEVEL]
    return None


def get_gui_log_level() -> int | None:
    from ubo_app.constants import GUI_LOG_LEVEL

    if GUI_LOG_LEVEL:
        import logging

        return logging.getLevelNamesMapping()[GUI_LOG_LEVEL]
    return None


def setup_loggers() -> Subscriptions:
    level = get_log_level()
    subscriptions: Subscriptions = []

    if level is not None:
        logger.setLevel(level)
        subscriptions.extend(add_file_handler(logger, level))
        subscriptions.extend(add_stdout_handler(logger, level))

    gui_level = get_gui_log_level()

    if gui_level is not None:
        import ubo_gui.logger

        ubo_gui.logger.logger.setLevel(gui_level)
        ubo_gui.logger.add_file_handler(gui_level)
        ubo_gui.logger.add_stdout_handler(gui_level)

    return subscriptions


__all__ = ('add_file_handler', 'add_stdout_handler', 'logger', 'setup_loggers')

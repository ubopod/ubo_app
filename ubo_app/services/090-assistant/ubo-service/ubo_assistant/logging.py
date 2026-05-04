"""Loguru file logging setup for the assistant subprocess."""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

DEFAULT_ASSISTANT_LOG_LEVEL = 'INFO'
DEFAULT_ASSISTANT_LOG_PATH = 'ubo-assistant.log'
LOG_FORMAT = '{time:YYYY-MM-DD HH:mm:ss.SSS} [{level}] {message}'
VALID_LOG_LEVELS = {
    'TRACE',
    'DEBUG',
    'INFO',
    'SUCCESS',
    'WARNING',
    'ERROR',
    'CRITICAL',
}


def _assistant_log_level() -> str:
    level = os.environ.get('UBO_ASSISTANT_LOG_LEVEL', DEFAULT_ASSISTANT_LOG_LEVEL)
    normalized_level = level.upper()
    if normalized_level in VALID_LOG_LEVELS:
        return normalized_level
    logger.warning(
        'Invalid UBO_ASSISTANT_LOG_LEVEL, falling back to INFO {extra}',
        extra={'level': level},
    )
    return DEFAULT_ASSISTANT_LOG_LEVEL


def setup_file_logging() -> int:
    """Add a rotating file sink for assistant subprocess logs."""
    log_path = Path(
        os.environ.get('UBO_ASSISTANT_LOG_PATH', DEFAULT_ASSISTANT_LOG_PATH),
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return logger.add(
        log_path,
        level=_assistant_log_level(),
        format=LOG_FORMAT,
        rotation='1 MB',
        retention=3,
    )

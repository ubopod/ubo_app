"""Optional Pipecat debugging integrations."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pipecat.observers.base_observer import BaseObserver
    from pipecat.pipeline.base_pipeline import BasePipeline

TRUTHY_VALUES = frozenset({'1', 'true', 'yes', 'on'})
WHISKER_ENABLED_ENV = 'UBO_ASSISTANT_WHISKER_ENABLED'
WHISKER_FILE_ENV = 'UBO_ASSISTANT_WHISKER_FILE'


class SupportsWhiskerObserver(Protocol):
    """Pipeline task surface needed to attach Whisker."""

    @property
    def pipeline(self) -> BasePipeline:
        """Return the task pipeline."""
        ...

    def add_observer(self, observer: BaseObserver) -> None:
        """Attach a Pipecat observer."""


def is_whisker_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether Whisker debugging should be enabled."""
    environment = environ if environ is not None else os.environ
    return environment.get(WHISKER_ENABLED_ENV, '').strip().lower() in TRUTHY_VALUES


def attach_whisker_observer(task: SupportsWhiskerObserver) -> bool:
    """Attach Whisker to a Pipecat pipeline task when explicitly enabled."""
    if not is_whisker_enabled():
        logger.debug('Whisker debugging disabled')
        return False

    try:
        from pipecat_whisker import WhiskerObserver

        file_name = os.environ.get(WHISKER_FILE_ENV)
        observer = (
            WhiskerObserver(task.pipeline, file_name=file_name)
            if file_name
            else WhiskerObserver(task.pipeline)
        )
        task.add_observer(observer)
    except Exception as exception:  # noqa: BLE001
        logger.warning(
            'Whisker debugging failed to initialize {extra}',
            extra={'exception': exception},
        )
        return False

    logger.info(
        'Whisker debugging enabled {extra}',
        extra={'file_name': os.environ.get(WHISKER_FILE_ENV)},
    )
    return True

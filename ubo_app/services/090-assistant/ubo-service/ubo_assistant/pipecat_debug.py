"""Optional Pipecat debugging integrations."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol, cast

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pipecat.observers.base_observer import BaseObserver
    from pipecat.pipeline.base_pipeline import BasePipeline
    from pipecat.pipeline.worker import PipelineWorker
    from pipecat.workers.base_worker import BaseWorker

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


def attach_whisker_observer(task: SupportsWhiskerObserver) -> BaseWorker | None:
    """Attach Whisker to a Pipecat pipeline task when explicitly enabled.

    Returns the Whisker sink so the caller can register it with the
    ``WorkerRunner`` via ``add_workers``. The sink is a Whisker 2.0 worker:
    its ``start()`` is what opens the recording file and the WS server, so it
    MUST be run as a worker — attaching the observer alone records nothing.
    Returns ``None`` when Whisker is disabled or fails to initialize.
    """
    if not is_whisker_enabled():
        logger.debug('Whisker debugging disabled')
        return None

    try:
        from pipecat_whisker import WhiskerFile, WhiskerObserver, WhiskerServer

        # Whisker 2.0 takes the worker plus an explicit sink. A bare file
        # capture uses the file-only sink (no WS server to bind); fall back to
        # the WS server (which also records to file) when no file is given.
        file_name = os.environ.get(WHISKER_FILE_ENV) or None
        sink = WhiskerFile(file_name) if file_name else WhiskerServer()
        observer = WhiskerObserver(cast('PipelineWorker', task), sink)
        task.add_observer(observer)
    except Exception as exception:  # noqa: BLE001
        logger.warning(
            'Whisker debugging failed to initialize {extra}',
            extra={'exception': exception},
        )
        return None

    logger.info(
        'Whisker debugging enabled {extra}',
        extra={'file_name': os.environ.get(WHISKER_FILE_ENV)},
    )
    return cast('BaseWorker', sink)

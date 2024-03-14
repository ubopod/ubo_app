"""Pytest configuration file for the tests."""
from __future__ import annotations

import asyncio
import atexit
import datetime
import gc
import sys
import threading
import weakref
from typing import TYPE_CHECKING, AsyncGenerator, Callable, Generator

import pytest
from redux import FinishAction
from snapshot import snapshot
from tenacity import retry, stop_after_delay, wait_exponential

from ubo_app.utils.garbage_collection import examine

if TYPE_CHECKING:
    from logging import Logger

    from ubo_app.menu import MenuApp

__all__ = ('app_context', 'snapshot')


@pytest.fixture(autouse=True, name='monkeypatch_atexit')
def _(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(atexit, 'register', lambda _: None)


modules_snapshot = set(sys.modules)


@pytest.fixture(autouse=True)
def _(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock external resources."""
    monkeypatch.setattr('psutil.cpu_percent', lambda **_: 50)
    monkeypatch.setattr(
        'psutil.virtual_memory',
        lambda *_: type('', (object,), {'percent': 50}),
    )

    class DateTime(datetime.datetime):
        @classmethod
        def now(cls: type[DateTime], tz: datetime.tzinfo | None = None) -> DateTime:
            _ = tz
            return DateTime(2023, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

    monkeypatch.setattr(datetime, 'datetime', DateTime)


@pytest.fixture()
def logger() -> Logger:
    import logging

    import ubo_app.logging
    from ubo_app.constants import LOG_LEVEL

    level = (
        getattr(
            ubo_app.logging,
            LOG_LEVEL,
            getattr(logging, LOG_LEVEL, logging.DEBUG),
        )
        if LOG_LEVEL
        else logging.DEBUG
    )

    logger = ubo_app.logging.get_logger('test')
    logger.setLevel(level)

    return logger


class AppContext:
    """Context object for tests running a menu application."""

    def set_app(self: AppContext, app: MenuApp) -> None:
        """Set the application."""
        self.app = app
        loop = asyncio.get_event_loop()
        self.task = loop.create_task(self.app.async_run(async_lib='asyncio'))


@pytest.fixture()
async def app_context(logger: Logger) -> AsyncGenerator[AppContext, None]:
    """Create the application."""
    import os

    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'

    import headless_kivy_pi.config

    headless_kivy_pi.config.setup_headless_kivy({'automatic_fps': True})

    context = AppContext()

    yield context

    assert context.task is not None, 'App not set for test'

    await context.task

    app_ref = weakref.ref(context.app)
    context.app.root.clear_widgets()

    del context.app
    del context.task

    gc.collect()
    app = app_ref()

    if app is not None:
        logger.debug(
            'Memory leak: failed to release app for test.',
            extra={
                'referrers': gc.get_referrers(app),
                'referents': gc.get_referents(app),
                'refcount': sys.getrefcount(app),
                'ref': app,
            },
        )
        gc.collect()
        for cell in gc.get_referrers(app):
            if type(cell).__name__ == 'cell':
                logger.debug('CELL EXAMINATION', extra={'cell': cell})
                examine(cell, depth_limit=2)
    assert app is None, 'Memory leak: failed to release app for test'

    from kivy.core.window import Window

    Window.close()

    for module in set(sys.modules) - modules_snapshot:
        if module != 'objc' and 'numpy' not in module and 'cache' not in module:
            del sys.modules[module]
    gc.collect()


@pytest.fixture()
def needs_finish() -> Generator:
    yield None

    from ubo_app.store import dispatch

    dispatch(FinishAction())


class WaitFor(threading.Thread):
    def __call__(
        self: WaitFor,
        satisfaction: Callable[[], None],
        *,
        timeout: float = 1,
    ) -> None:
        self.retry = retry(
            stop=stop_after_delay(timeout),
            wait=wait_exponential(multiplier=0.5),
        )(satisfaction)
        self.start()

    def run(self: WaitFor) -> None:
        self.retry()


@pytest.fixture()
def wait_for() -> Generator[WaitFor, None, None]:
    context = WaitFor()
    yield context
    context.join()

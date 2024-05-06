"""Fixtures for the application tests."""

from __future__ import annotations

import asyncio
import gc
import logging
import sys
import weakref
from typing import TYPE_CHECKING

import pytest

from ubo_app.setup import setup

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from _pytest.fixtures import SubRequest

    from ubo_app.menu_app.menu import MenuApp

modules_snapshot = set(sys.modules)


class AppContext:
    """Context object for tests running a menu application."""

    def __init__(self: AppContext, request: SubRequest) -> None:
        """Initialize the context."""
        self.request = request

    def set_app(self: AppContext, app: MenuApp) -> None:
        """Set the application."""
        from ubo_app.utils.loop import setup_event_loop

        setup_event_loop()
        self.app = app
        loop = asyncio.get_event_loop()
        self.task = loop.create_task(self.app.async_run(async_lib='asyncio'))

    async def clean_up(self: AppContext) -> None:
        """Clean up the application."""
        assert hasattr(self, 'task'), 'App not set for test'

        self.app.stop()
        await self.task

        app_ref = weakref.ref(self.app)
        self.app.root.clear_widgets()

        await asyncio.sleep(0.5)
        del self.app
        del self.task

        gc.collect()
        app = app_ref()

        if app is not None and self.request.session.testsfailed == 0:
            logging.getLogger().debug(
                'Memory leak: failed to release app for test.',
                extra={
                    'refcount': sys.getrefcount(app),
                    'referrers': gc.get_referrers(app),
                    'ref': app_ref,
                },
            )
            gc.collect()
            for cell in gc.get_referrers(app):
                if type(cell).__name__ == 'cell':
                    from ubo_app.utils.garbage_collection import examine

                    logging.getLogger().debug(
                        'CELL EXAMINATION',
                        extra={'cell': cell},
                    )
                    examine(cell, depth_limit=2)
            assert app is None, 'Memory leak: failed to release app for test'

        from kivy.core.window import Window

        Window.close()

        for module in set(sys.modules) - modules_snapshot:
            if module != 'objc' and 'numpy' not in module and 'cache' not in module:
                del sys.modules[module]
        gc.collect()


@pytest.fixture()
async def app_context(
    request: SubRequest,
) -> AsyncGenerator[AppContext, None]:
    """Create the application."""
    import os

    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'
    os.environ['KIVY_METRICS_DENSITY'] = '1'

    setup()

    import headless_kivy_pi.config

    headless_kivy_pi.config.setup_headless_kivy({'automatic_fps': True})

    context = AppContext(request)

    yield context

    await context.clean_up()

    assert not hasattr(context, 'app'), 'App not cleaned up'

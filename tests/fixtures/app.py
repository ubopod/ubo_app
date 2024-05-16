"""Fixtures for the application tests."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import sys
import weakref
from pathlib import Path
from typing import TYPE_CHECKING

import platformdirs
import pytest

from ubo_app.constants import PERSISTENT_STORE_PATH
from ubo_app.setup import setup

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from _pytest.fixtures import SubRequest
    from pyfakefs.fake_filesystem import FakeFilesystem

    from ubo_app.menu_app.menu import MenuApp

modules_snapshot = set(sys.modules)


class AppContext:
    """Context object for tests running a menu application."""

    def __init__(self: AppContext, request: SubRequest, *, fs: FakeFilesystem) -> None:
        """Initialize the context."""
        self.request = request
        self.persistent_store_data = {}
        self.fs = fs

    def set_persistent_storage_value(
        self: AppContext,
        key: str,
        *,
        value: object,
    ) -> None:
        """Set initial value in persistent store."""
        assert not hasattr(
            self,
            'app',
        ), "Can't set persistent storage values after app has been set"
        self.persistent_store_data[key] = value

    def set_app(self: AppContext, app: MenuApp) -> None:
        """Set the application."""
        self.fs.create_file(
            PERSISTENT_STORE_PATH.as_posix(),
            contents=json.dumps(self.persistent_store_data),
        )

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


@pytest.fixture()
async def app_context(request: SubRequest) -> AsyncGenerator[AppContext, None]:
    """Create the application."""
    import os

    from pyfakefs.fake_filesystem_unittest import Patcher

    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'
    os.environ['KIVY_METRICS_DENSITY'] = '1'

    import headless_kivy_pi.config

    headless_kivy_pi.config.setup_headless_kivy(
        {'automatic_fps': True, 'flip_vertical': True},
    )

    current_path = Path()
    with Patcher(
        additional_skip_names=[
            'redux_pytest.fixtures',
            'tests.fixtures.snapshot',
            'pathlib',
        ],
    ) as patcher:
        assert patcher.fs is not None

        patcher.fs.add_real_paths(
            [
                (current_path / 'tests').absolute().as_posix(),
                (current_path / 'ubo_app').absolute().as_posix(),
                platformdirs.user_cache_dir('pypoetry'),
            ],
        )

        setup()

        context = AppContext(request, fs=patcher.fs)

        yield context

        await context.clean_up()

        assert not hasattr(context, 'app'), 'App not cleaned up'

        del context
        del patcher

        for module in set(sys.modules) - modules_snapshot:
            if (
                module != 'objc'
                and 'numpy' not in module
                and 'kivy.cache' not in module
            ):
                del sys.modules[module]

        gc.collect()

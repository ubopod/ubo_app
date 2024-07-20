"""Fixtures for the application tests."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import logging
import sys
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import platformdirs
import pytest
from pyfakefs.fake_filesystem_unittest import Patcher
from str_to_bool import str_to_bool

from ubo_app.constants import (
    HEIGHT,
    MAIN_LOOP_GRACE_PERIOD,
    PERSISTENT_STORE_PATH,
    WIDTH,
)
from ubo_app.setup import setup

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from types import TracebackType

    from _pytest.fixtures import SubRequest

    from ubo_app.menu_app.menu import MenuApp

# It needs to be included in `modules_snapshot`
__import__('numpy')
modules_snapshot = set(sys.modules)


class AppContext:
    """Context object for tests running a menu application."""

    def __init__(self: AppContext, request: SubRequest) -> None:
        """Initialize the context."""
        self.request = request
        self.persistent_store_data = {}

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
        PERSISTENT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PERSISTENT_STORE_PATH.write_text(json.dumps(self.persistent_store_data))

        from ubo_app.utils.loop import start_event_loop

        start_event_loop()
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

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(MAIN_LOOP_GRACE_PERIOD + 0.2)

        del self.app
        del self.task

        gc.collect()
        app = app_ref()

        if app is not None and self.request.session.testsfailed == 0:
            logging.debug(
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

                    logging.debug(
                        'CELL EXAMINATION',
                        extra={'cell': cell},
                    )
                    examine(cell, depth_limit=2)
            assert app is None, 'Memory leak: failed to release app for test'

        from kivy.core.window import Window

        Window.close()

        from ubo_app.utils import IS_RPI

        if IS_RPI:
            from RPi import GPIO  # pyright: ignore [reportMissingModuleSource]

            GPIO.cleanup(17)


class ConditionalFSWrapper:
    """Conditional wrapper for the fake filesystem."""

    def __init__(
        self: ConditionalFSWrapper,
        *,
        condition: bool,
    ) -> None:
        """Initialize the wrapper."""
        self.condition = condition

        # These needs to be imported before setting up fake fs
        import coverage

        from ubo_app.utils import IS_RPI

        if IS_RPI:
            picamera_skip_modules = [
                'picamera2',
                'picamera2.allocators.dmaallocator',
                'picamera2.dma_heap',
            ]
        else:
            picamera_skip_modules = []
        import headless_kivy_pytest.fixtures.snapshot
        import pyzbar.pyzbar
        import redux_pytest.fixtures.snapshot

        self.patcher = Patcher(
            additional_skip_names=[
                coverage,
                pytest,
                pyzbar.pyzbar,
                headless_kivy_pytest.fixtures.snapshot,
                redux_pytest.fixtures.snapshot,
                *picamera_skip_modules,
            ],
        )

    def __enter__(self: ConditionalFSWrapper) -> Patcher | None:
        """Enter the context."""
        if self.condition:
            import os

            real_paths = [
                path
                for path in os.environ.get('UBO_TEST_REAL_PATHS', '').split(':')
                if path
            ]
            patcher = self.patcher.__enter__()
            assert patcher.fs is not None

            patcher.fs.add_real_paths(
                [
                    os.environ['TEST_ROOT_PATH'] + '/ubo_app',
                    os.environ['TEST_ROOT_PATH'] + '/tests/data',
                    platformdirs.user_cache_dir('pypoetry'),
                    *real_paths,
                ],
            )
            patcher.fs.create_file(
                '/proc/device-tree/hat/custom_0',
                contents='{"serial_number": "<TEST_SERIAL_NUMBER>"}',
            )

            return patcher
        return None

    def __exit__(
        self: ConditionalFSWrapper,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the context."""
        if self.condition:
            return self.patcher.__exit__(exc_type, exc_value, traceback)
        return None


def _setup_headless_kivy() -> None:
    import os

    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'
    os.environ['KIVY_METRICS_DENSITY'] = '1'
    if sys.platform == 'darwin':
        # Some dirty patches to make Kivy generate the same window size on macOS
        from kivy.config import Config

        os.environ['KIVY_DPI'] = '96'
        original_config_set = Config.set

        def patched_config_set(category: str, key: str, value: str) -> None:
            if category == 'graphics':
                if key == 'width':
                    value = str(int(value) // 2)
                if key == 'height':
                    value = str(int(value) // 2)
            original_config_set(category, key, value)

        Config.set = patched_config_set

    from ubo_app.utils import IS_RPI

    if not IS_RPI:
        from kivy.config import Config

        Config.set('graphics', 'window_state', 'hidden')

    import headless_kivy.config

    from ubo_app.display import render_on_display

    headless_kivy.config.setup_headless_kivy(
        {
            'callback': render_on_display,
            'automatic_fps': True,
            'flip_vertical': True,
            'width': WIDTH,
            'height': HEIGHT,
        },
    )


@pytest.fixture()
async def app_context(
    request: SubRequest,
    _monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AppContext, None]:
    """Create the application."""
    _ = _monkeypatch
    setup()
    _setup_headless_kivy()

    import os

    from ubo_app.logging import setup_logging

    setup_logging()

    os.environ['TEST_ROOT_PATH'] = Path().absolute().as_posix()
    should_use_fake_fs = (
        request.config.getoption(
            '--use-fake-filesystem',
            default=cast(
                Any,
                str_to_bool(os.environ.get('UBO_TEST_USE_FAKE_FILESYSTEM', 'false'))
                == 1,
            ),
        )
        is True
    )

    with ConditionalFSWrapper(condition=should_use_fake_fs) as patcher:
        context = AppContext(request)

        yield context

        await context.clean_up()

        del patcher

    assert not hasattr(context, 'app'), 'App not cleaned up'

    del context

    for module_name in set(sys.modules) - modules_snapshot:
        if (
            module_name != 'objc'
            and 'kivy.cache' not in module_name
            and 'sdbus' not in module_name
            and 'ubo_app.display' not in module_name
        ):
            del sys.modules[module_name]

    gc.collect()

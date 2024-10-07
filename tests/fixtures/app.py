"""Fixtures for the application tests."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import sys
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import dotenv
import pytest
from pyfakefs.fake_filesystem_unittest import Patcher
from str_to_bool import str_to_bool

modules_snapshot = set(sys.modules).union(
    {
        'kivy.cache',
        'numpy',
        'ubo_app.display',
        'ubo_app.utils.monitor_unit',
    },
)


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from types import TracebackType

    from _pytest.fixtures import SubRequest

    from ubo_app.menu_app.menu import MenuApp


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
        from ubo_app.constants import PERSISTENT_STORE_PATH

        PERSISTENT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PERSISTENT_STORE_PATH.write_text(json.dumps(self.persistent_store_data))
        self.app = app
        self.loop = asyncio.get_event_loop()
        self.task = self.loop.create_task(self.app.async_run(async_lib='asyncio'))

        from ubo_app.service import start_event_loop_thread

        start_event_loop_thread(asyncio.new_event_loop())

    async def clean_up(self: AppContext) -> None:
        """Clean up the application."""
        from redux import FinishAction

        import ubo_app.service
        from ubo_app.store.main import store

        store.dispatch(FinishAction())

        assert hasattr(self, 'task'), 'App not set for test'

        self.app.stop()

        await self.task

        app_ref = weakref.ref(self.app)
        self.app.root.clear_widgets()

        ubo_app.service.worker_thread.is_finished.wait()

        del self.app
        del self.task

        gc.collect()
        app = app_ref()

        if app is not None and self.request.session.testsfailed == 0:
            logging.info(
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
        use_fake_fs: bool,
    ) -> None:
        """Initialize the wrapper."""
        if use_fake_fs:
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
        else:
            self.patcher = None

    def __enter__(self: ConditionalFSWrapper) -> Patcher | None:
        """Enter the context."""
        if self.patcher:
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
                    '.venv',
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
        if self.patcher:
            return self.patcher.__exit__(exc_type, exc_value, traceback)
        return None


def _setup_headless_kivy() -> None:
    import os

    from ubo_app.constants import HEIGHT, WIDTH

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


@pytest.fixture
async def app_context(
    request: SubRequest,
    mock_environment: None,
) -> AsyncGenerator[AppContext, None]:
    """Create the application."""
    _ = mock_environment

    from ubo_app.setup import setup

    dotenv.load_dotenv(Path(__file__).parent / '.env')
    setup()
    _setup_headless_kivy()

    import os

    from ubo_app.logging import setup_logging

    setup_logging()

    os.environ['TEST_ROOT_PATH'] = Path().absolute().as_posix()
    should_use_fake_fs = (
        request.config.getoption(
            '--use-fakefs',
            default=cast(
                Any,
                str_to_bool(os.environ.get('UBO_TEST_USE_FAKEFS', 'false')) == 1,
            ),
        )
        is True
    )

    with ConditionalFSWrapper(use_fake_fs=should_use_fake_fs) as patcher:
        context = AppContext(request)

        yield context

        await context.clean_up()
    del patcher

    assert not hasattr(context, 'app'), 'App not cleaned up'

    del context

    for module_name in set(sys.modules) - modules_snapshot:
        if not module_name.startswith('sdbus'):
            del sys.modules[module_name]

    gc.collect()

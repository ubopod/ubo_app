"""Fixtures for the application tests."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import sys
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import dotenv
import pytest
from pyfakefs.fake_filesystem_unittest import Patcher
from str_to_bool import str_to_bool

from ubo_app.constants import TEST_INVESTIGATION_MODE
from ubo_app.logger import logger

modules_snapshot = set(sys.modules).union(
    {
        'kivy.cache',
        'numpy',
        # This need to persist because sdbus interfaces can't be unloaded
        'ubo_app.utils.dbus_interfaces',
    },
)


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from types import TracebackType

    from _pytest.fixtures import SubRequest  # pyright: ignore[reportPrivateImportUsage]

    from ubo_app.menu_app.menu import MenuApp
    from ubo_app.utils.garbage_collection import ClosureTracker


class AppContext:
    """Context object for tests running a menu application."""

    def __init__(
        self: AppContext,
        request: SubRequest,
        tracker: ClosureTracker | None = None,
    ) -> None:
        """Initialize the context."""
        self.request = request
        self.persistent_store_data = {}
        self._cleanup_is_called = False
        self.tracker = tracker

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

    def set_app(self: AppContext, app: MenuApp | None = None) -> None:
        """Set the application."""
        from ubo_app.constants import PERSISTENT_STORE_PATH

        PERSISTENT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PERSISTENT_STORE_PATH.write_text(json.dumps(self.persistent_store_data))

        from ubo_app.service import start_event_loop_thread

        start_event_loop_thread(asyncio.new_event_loop())

        from ubo_app.menu_app.menu import MenuApp

        if app is None:
            app = MenuApp()

        self.app = app
        self.loop = asyncio.get_event_loop()
        self.task = self.loop.create_task(self.app.async_run(async_lib='asyncio'))

    async def _cleanup(self: AppContext) -> None:
        """Clean up the application."""
        if self._cleanup_is_called:
            return
        self._cleanup_is_called = True
        from redux import FinishAction

        from ubo_app.store.main import scheduler, store

        store.dispatch(FinishAction())
        store.wait_for_event_handlers()

        import ubo_app.service

        assert hasattr(self, 'task'), 'App not set for test'

        scheduler.join()

        from kivy.clock import Clock

        while events := Clock.get_events():
            for event in list(events):
                event.cancel()

        self.app.root.clear_widgets()
        if not self.app.is_stopped:
            self.app.stop()

        await self.task

        app_ref = weakref.ref(self.app)

        ubo_app.service.worker_thread.is_finished.wait()

        del self.app
        del self.task

        await asyncio.sleep(1)
        gc.collect()

        if app_ref() is not None and self.request.session.testsfailed == 0:
            logger.info(
                'Memory leak: failed to release app for test.',
                extra={
                    'refcount': sys.getrefcount(app_ref()),
                    'referrers': gc.get_referrers(app_ref()),
                    'ref': app_ref,
                },
            )
            gc.collect()

            if TEST_INVESTIGATION_MODE and self.tracker:
                logger.info(
                    'Cells info',
                    extra={
                        'cells': [
                            self.tracker.get_cell_info(cell)
                            for cell in gc.get_referrers(app_ref())
                            if type(cell).__name__ == 'cell'
                        ],
                    },
                )
                with contextlib.suppress(ImportError):
                    import objgraph

                    objgraph.show_refs(
                        [app_ref()],
                        filename='/tmp/app_referrers.png',  # noqa: S108
                    )

                with contextlib.suppress(ImportError):
                    import ipdb  # noqa: T100

                    ipdb.set_trace()  # noqa: T100

            for cell in gc.get_referrers(app_ref()):
                if type(cell).__name__ == 'cell':
                    from ubo_app.utils.garbage_collection import examine

                    logger.debug(
                        'CELL EXAMINATION',
                        extra={'cell': cell},
                    )
                    examine(cell, depth_limit=2)
            assert app_ref() is None, 'Memory leak: failed to release app for test'

        from kivy.core.window import Window

        Window.close()


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


def _setup_kivy() -> None:
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

        Config.set(
            'graphics',
            'window_state',
            'visible' if TEST_INVESTIGATION_MODE else 'hidden',
        )
        Config.set('graphics', 'fbo', 'force-hardware')
        Config.set('graphics', 'fullscreen', '0')
        Config.set('graphics', 'multisamples', '1')
        Config.set('graphics', 'vsync', '0')


def _setup_headless_kivy() -> None:
    import headless_kivy.config

    from ubo_app.constants import HEIGHT, WIDTH
    from ubo_app.display import render_on_display

    headless_kivy.config.setup_headless_kivy(
        headless_kivy.config.SetupHeadlessConfig(
            callback=render_on_display,
            flip_vertical=True,
            width=WIDTH,
            height=HEIGHT,
        ),
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
    _setup_kivy()
    setup()
    _setup_headless_kivy()

    import os

    from ubo_app.logger import setup_loggers

    logger_cleanups = setup_loggers()

    os.environ['TEST_ROOT_PATH'] = Path().absolute().as_posix()
    should_use_fake_fs = (
        request.config.getoption(
            '--use-fakefs',
            default=cast(
                'Any',
                str_to_bool(os.environ.get('UBO_TEST_USE_FAKEFS', 'false')),
            ),
        )
        is True
    )

    tracker = None
    if TEST_INVESTIGATION_MODE:
        from ubo_app.utils.garbage_collection import ClosureTracker

        tracker = ClosureTracker()
        tracker.start_tracking()

    try:
        with ConditionalFSWrapper(use_fake_fs=should_use_fake_fs) as patcher:
            context = AppContext(request, tracker)

            yield context

            await context._cleanup()  # noqa: SLF001
            for cleanup in logger_cleanups:
                cleanup()

        del patcher

        assert not hasattr(context, 'app'), 'App not cleaned up'

        del context

        for module_name in set(sys.modules) - modules_snapshot:
            if not module_name.startswith('sdbus'):
                del sys.modules[module_name]

        gc.collect()
    finally:
        if TEST_INVESTIGATION_MODE and tracker:
            tracker.stop_tracking()

"""Fixtures for the application tests."""

from __future__ import annotations

import gc
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import dotenv
import pytest
import redux  # noqa: F401 -- load redux before the modules_snapshot below
from pyfakefs.fake_filesystem_unittest import Patcher
from str_to_bool import str_to_bool

from ubo_app.logger import logger

# Captured at import time. The cleanup at the end of `app_context` deletes
# every module NOT in this set so each integration test starts from a clean
# slate. The `import redux` above is load-bearing: without it redux's
# submodules are not in sys.modules yet, get deleted on first cleanup, and
# the next test sees a brand-new `redux.basic_types.FinishEvent` class while
# the redux store still holds handlers registered against the OLD class. The
# store then has TWO FinishEvent keys in `_event_handlers`, handlers don't
# fire on dispatch, and downstream tests timeout waiting for service
# lifecycle events that never propagate.
modules_snapshot = set(sys.modules).union(
    {
        # This need to persist because sdbus interfaces can't be unloaded
        'ubo_app.utils.dbus_interfaces',
    },
)

# Everything under this root is a pytest-collected module (test files,
# fixtures, helpers). The cleanup below must never evict them: pytest holds
# the only reference and never re-imports them, so deleting them from
# `sys.modules` only breaks `sys.modules[cls.__module__]` lookups later —
# betterproto's lazy metadata, `typing.get_type_hints`, `pickle` — for
# classes defined in test modules.
TESTS_ROOT = Path(__file__).resolve().parent.parent


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable
    from types import TracebackType

    from _pytest.fixtures import SubRequest  # pyright: ignore[reportPrivateImportUsage]


# Background threads that must fully exit before the per-test module cleanup
# deletes their owning modules. A thread that outlives module deletion rebinds
# to the next test's freshly re-imported singletons (e.g. a loop-less
# ``worker_thread``), which crashes its Side Effect Runner and hangs the next
# test waiting on an event that never fires.
_BACKGROUND_THREAD_NAMES = ('Side Effect Runner', 'Scheduler Thread', 'Worker Thread')


def _join_background_threads(
    names: Iterable[str],
    *,
    timeout: float,
) -> None:
    """Block until the named background threads have stopped.

    Returns once no thread in ``names`` is alive, or after ``timeout`` seconds.
    Surviving threads are logged so a leak is visible rather than silently
    corrupting the next test.
    """
    import threading
    import time

    wanted = set(names)
    deadline = time.monotonic() + timeout

    def _pending() -> list[threading.Thread]:
        current = threading.current_thread()
        return [
            thread
            for thread in threading.enumerate()
            if thread.name in wanted and thread is not current and thread.is_alive()
        ]

    for thread in _pending():
        thread.join(timeout=max(0.0, deadline - time.monotonic()))

    survivors = [thread.name for thread in _pending()]
    if survivors:
        logger.warning('Background threads still alive after teardown: %s', survivors)


class AppContext:
    """Context object for tests running core in-process with GUI as subprocess."""

    def __init__(
        self: AppContext,
        request: SubRequest,
    ) -> None:
        """Initialize the context."""
        self.request = request
        self._cleanup_is_called = False
        self.gui_process: subprocess.Popen[bytes] | None = None
        self._subscriptions: list[Any] = []

    def set_app(self: AppContext) -> None:
        """Start core in-process and GUI client as subprocess."""
        from ubo_app.constants import GRPC_LISTEN_PORT

        # Start gRPC server on the worker thread
        from ubo_app.rpc.server import serve as grpc_serve
        from ubo_app.service import worker_thread

        worker_thread.run_coroutine(grpc_serve())

        # Set up side effects and menu event handlers
        from ubo_app.side_effects import setup_side_effects

        self._subscriptions.extend(setup_side_effects())

        from ubo_app.store.core.menu_event_handlers import setup_menu_event_handlers

        self._subscriptions.extend(setup_menu_event_handlers())

        # Find and spawn the GUI client subprocess
        gui_exe = self._find_gui_executable()
        if gui_exe is not None:
            import os

            env = os.environ.copy()
            env['HEADLESS_KIVY_DEBUG'] = 'true'
            env['KIVY_NO_ARGS'] = '1'
            env['KIVY_NO_CONFIG'] = '1'
            env['KIVY_NO_FILELOG'] = '1'
            env['KIVY_NO_CONSOLELOG'] = '1'
            env['UBO_TEST_ENV'] = 'true'
            # Remove venv vars so the GUI subprocess uses its own venv
            env.pop('VIRTUAL_ENV', None)
            env.pop('UV_PROJECT_ENVIRONMENT', None)
            # Pass verbose flag to see GUI client logs
            gui_args = ['--verbose']

            logger.info('Starting GUI client: %s', gui_exe)
            try:
                self.gui_process = subprocess.Popen(  # noqa: S603
                    [
                        str(gui_exe),
                        '--host',
                        'localhost',
                        '--port',
                        str(GRPC_LISTEN_PORT),
                        *gui_args,
                    ],
                    env=env,
                )
                logger.info(
                    'GUI client started (pid=%d)',
                    self.gui_process.pid,
                )
            except FileNotFoundError:
                logger.warning(
                    'Failed to start ubo-gui-client at %s, running without GUI',
                    gui_exe,
                )
                self.gui_process = None

    @staticmethod
    def _find_gui_executable() -> Path | None:
        """Find the ubo-gui-client executable."""
        # Check the GUI subpackage's venv
        gui_venv = (
            Path(__file__).parent.parent.parent
            / 'ubo_app'
            / 'gui'
            / '.venv'
            / 'bin'
            / 'ubo-gui-client'
        )
        if gui_venv.is_file():
            return gui_venv

        # Check the main venv
        import os

        bin_dir = Path(sys.executable).parent
        candidate = bin_dir / 'ubo-gui-client'
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

        logger.warning('ubo-gui-client executable not found, running without GUI')
        return None

    async def _cleanup(self: AppContext) -> None:
        """Clean up the application."""
        if self._cleanup_is_called:
            return
        self._cleanup_is_called = True

        # Close the gRPC server first to release the port before shutdown.
        # Wait on an explicit completion signal instead of a fixed sleep so
        # that shutdown is deterministic and avoids port-reuse flakes.
        import threading

        import ubo_app.service
        from ubo_app.rpc.server import close_server

        server_closed = threading.Event()

        async def _close_and_signal() -> None:
            try:
                await close_server()
            finally:
                server_closed.set()

        ubo_app.service.worker_thread.run_coroutine(_close_and_signal())

        # Wait up to 5s for the server to actually close
        if not server_closed.wait(timeout=5):
            logger.warning('gRPC server did not close within 5s')

        from redux import FinishAction

        from ubo_app.store.main import scheduler, store

        store.dispatch(FinishAction())
        store.wait_for_event_handlers()

        # FinishAction enqueues the ``None`` sentinel that ends each Side Effect
        # Runner's loop. Join those threads now so a leaked runner can't fire a
        # side effect against the next test's freshly re-imported (loop-less)
        # worker_thread and crash itself, hanging the next test.
        _join_background_threads({'Side Effect Runner'}, timeout=10)

        # Belt-and-braces: FinishAction is already wired to scheduler.stop via
        # on_finish in ubo_app/store/main.py, but call it explicitly so a
        # missed/lost FinishAction can't strand the scheduler thread and hang
        # the entire pytest process during fixture teardown.
        scheduler.stop()
        scheduler.join(timeout=10)
        if scheduler.is_alive():
            logger.warning('scheduler did not join within 10s')

        # Clean up subscriptions
        for cleanup in self._subscriptions:
            cleanup()
        self._subscriptions.clear()

        # Terminate GUI subprocess
        if self.gui_process is not None:
            self.gui_process.terminate()
            try:
                self.gui_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.gui_process.kill()
                self.gui_process.wait()
            self.gui_process = None

        if not ubo_app.service.worker_thread.is_finished.wait(timeout=10):
            logger.warning('worker_thread did not finish within 10s')

        gc.collect()


class ConditionalFSWrapper:
    """Conditional wrapper for the fake file system."""

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
            import pyzbar.pyzbar
            import redux_pytest.fixtures.snapshot

            import tests.fixtures.snapshot

            self.patcher = Patcher(
                additional_skip_names=[
                    coverage,
                    pytest,
                    pyzbar.pyzbar,
                    tests.fixtures.snapshot,
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


@pytest.fixture
async def app_context(
    request: SubRequest,
    mock_environment: None,
) -> AsyncGenerator[AppContext, None]:
    """Create the application."""
    _ = mock_environment

    from ubo_app.setup_headless import setup_headless

    dotenv.load_dotenv(Path(__file__).parent / '.env')
    setup_headless()

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

    try:
        with ConditionalFSWrapper(use_fake_fs=should_use_fake_fs) as patcher:
            context = AppContext(request)

            yield context

            await context._cleanup()  # noqa: SLF001
            for cleanup in logger_cleanups:
                cleanup()

        del patcher

        assert not hasattr(context, 'gui_process') or context.gui_process is None, (
            'GUI process not cleaned up'
        )

        del context

        # Restore stdio before module cleanup.  Kivy replaces sys.stderr/
        # sys.stdout with LoggerStderr/LoggerStdout wrappers.  After module
        # cleanup the old wrappers reference stale Logger objects, causing
        # infinite recursion when Kivy is re-imported by the next test.
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

        # Hard gate: never delete this test's modules while one of its background
        # threads is still alive, or the survivor rebinds to the next test's
        # half-initialized singletons and crashes/hangs it.
        _join_background_threads(_BACKGROUND_THREAD_NAMES, timeout=10)

        # The whole betterproto/ubo_bindings stack must persist as a unit: the
        # generated proto message classes subclass ``betterproto.Message`` and
        # betterproto resolves type hints lazily via ``sys.modules[cls.__module__]``.
        # Pinning only the leaf proto module (e.g. ``ubo_bindings.ubo.v1``) while
        # ``betterproto`` and the sibling proto modules get re-imported leaves the
        # persisted classes inheriting the OLD ``betterproto.Message`` — a cross-
        # version mismatch that breaks every gRPC round-trip (and hangs the flow
        # tests). Skip both families so the proto object graph stays consistent.
        for module_name in set(sys.modules) - modules_snapshot:
            if module_name.startswith(
                ('sdbus', 'gpiozero', 'lgpio', 'betterproto', 'ubo_bindings'),
            ):
                continue
            module_file = getattr(sys.modules.get(module_name), '__file__', None)
            if module_file:
                try:
                    if TESTS_ROOT in Path(module_file).resolve().parents:
                        continue
                except (OSError, ValueError):
                    pass
            del sys.modules[module_name]

        gc.collect()
    finally:
        pass

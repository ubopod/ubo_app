"""Process supervisor that spawns ubo-core and ubo-gui-client as children."""

from __future__ import annotations

import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger('ubo_supervisor')
logging.basicConfig(level=logging.INFO)

# Default gRPC connection parameters (same env vars as constants/__init__.py)
_GRPC_HOST = os.environ.get('UBO_GRPC_LISTEN_ADDRESS', '127.0.0.1')
_GRPC_PORT = int(os.environ.get('UBO_GRPC_LISTEN_PORT', '50051'))

_POLL_INTERVAL = 0.5  # seconds between gRPC readiness checks
_POLL_TIMEOUT = 30.0  # max seconds to wait for gRPC server
_CORE_SHUTDOWN_TIMEOUT = 30.0  # max seconds to wait for core graceful shutdown


def _find_executable(name: str) -> Path | None:
    """Find an executable in the venv or the GUI subpackage's venv."""
    # First check the main venv bin directory
    bin_dir = Path(sys.executable).parent
    candidate = bin_dir / name
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate

    # Also check the GUI subpackage's venv (ubo_app/gui/.venv/bin/)
    gui_venv = Path(__file__).parent / 'gui' / '.venv' / 'bin' / name
    if gui_venv.is_file() and os.access(gui_venv, os.X_OK):
        return gui_venv

    return None


def _wait_for_grpc(host: str, port: int, timeout: float) -> bool:
    """Poll TCP connect until gRPC server is reachable or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(_POLL_INTERVAL)
    return False


def _terminate_process(proc: subprocess.Popen[bytes], timeout: float = 5) -> None:
    """Send SIGTERM and wait briefly, then SIGKILL if still alive."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _spawn_core(core_exe: Path) -> subprocess.Popen[bytes]:
    """Spawn the ubo-core process in its own session."""
    return subprocess.Popen(  # noqa: S603
        [str(core_exe)],
        start_new_session=True,
    )


def _spawn_gui(
    gui_exe: Path,
    host: str,
    port: int,
) -> subprocess.Popen[bytes]:
    """Spawn the ubo-gui-client process in its own session."""
    return subprocess.Popen(  # noqa: S603
        [str(gui_exe), '--host', host, '--port', str(port)],
        start_new_session=True,
    )


def _wait_for_core_grpc(
    core_proc: subprocess.Popen[bytes],
    host: str,
    port: int,
) -> None:
    """Wait for the gRPC server to become reachable, or exit on failure."""
    logger.info('Waiting for gRPC server at %s:%d...', host, port)
    if _wait_for_grpc(host, port, _POLL_TIMEOUT):
        return

    if core_proc.poll() is not None:
        logger.error(
            'ubo-core exited during startup with code %d',
            core_proc.returncode,
        )
        sys.exit(core_proc.returncode or 1)

    logger.error('gRPC server not ready after %ss', _POLL_TIMEOUT)
    _terminate_process(core_proc)
    sys.exit(1)


def _monitor_children(
    core_proc: subprocess.Popen[bytes],
    gui_proc: subprocess.Popen[bytes],
    shutting_down: list[bool],
) -> None:
    """Block until core exits or GUI dies unexpectedly.

    If GUI dies during shutdown, we keep waiting for core to finish its
    graceful shutdown. If GUI dies outside of shutdown, we return so the
    caller can initiate shutdown.
    """
    while core_proc.poll() is None:
        if gui_proc.poll() is not None and not shutting_down[0]:
            logger.info(
                'ubo-gui-client exited unexpectedly with code %d',
                gui_proc.returncode,
            )
            return
        time.sleep(0.5)

    logger.info('ubo-core exited with code %d', core_proc.returncode)


def _install_signal_handlers(
    core_proc: subprocess.Popen[bytes],
    gui_proc_holder: list[subprocess.Popen[bytes] | None],
    shutting_down: list[bool],
) -> None:
    """Install SIGINT/SIGTERM handlers for ordered child shutdown."""

    def _handle_sigint(_signum: int, _frame: object) -> None:
        if shutting_down[0]:
            logger.warning('Second interrupt received, forcing shutdown')
            if core_proc.poll() is None:
                core_proc.terminate()
            if gui_proc_holder[0] is not None and gui_proc_holder[0].poll() is None:
                gui_proc_holder[0].terminate()
            return

        shutting_down[0] = True
        logger.info('Interrupt received, initiating graceful shutdown')
        if core_proc.poll() is None:
            core_proc.send_signal(signal.SIGINT)

    def _handle_sigterm(_signum: int, _frame: object) -> None:
        shutting_down[0] = True
        logger.info('SIGTERM received, forwarding to children')
        if core_proc.poll() is None:
            core_proc.terminate()
        if gui_proc_holder[0] is not None and gui_proc_holder[0].poll() is None:
            gui_proc_holder[0].terminate()

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigterm)


def _cleanup_children(
    core_proc: subprocess.Popen[bytes],
    gui_proc: subprocess.Popen[bytes] | None,
    shutting_down: list[bool],
) -> None:
    """Wait for core graceful shutdown, then terminate GUI."""
    if core_proc.poll() is None:
        if not shutting_down[0]:
            core_proc.send_signal(signal.SIGINT)
        try:
            core_proc.wait(timeout=_CORE_SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.warning('Core did not exit in time, terminating')
            _terminate_process(core_proc)

    if gui_proc is not None:
        _terminate_process(gui_proc)


def main() -> None:
    """Spawn ubo-core and ubo-gui-client, monitor them, and propagate signals."""
    core_exe = _find_executable('ubo-core')
    if core_exe is None:
        logger.error(
            'ubo-core executable not found in %s',
            Path(sys.executable).parent,
        )
        sys.exit(1)

    gui_exe = _find_executable('ubo-gui-client')
    headless_only = gui_exe is None
    if headless_only:
        logger.warning('ubo-gui-client not found, running headless only')

    core_proc = _spawn_core(core_exe)
    shutting_down: list[bool] = [False]
    gui_proc_holder: list[subprocess.Popen[bytes] | None] = [None]

    _install_signal_handlers(core_proc, gui_proc_holder, shutting_down)

    try:
        if headless_only:
            core_proc.wait()
            return

        _wait_for_core_grpc(core_proc, _GRPC_HOST, _GRPC_PORT)

        gui_proc_holder[0] = _spawn_gui(gui_exe, _GRPC_HOST, _GRPC_PORT)

        _monitor_children(core_proc, gui_proc_holder[0], shutting_down)

    finally:
        _cleanup_children(core_proc, gui_proc_holder[0], shutting_down)

    exit_code = 0
    if core_proc.returncode:
        exit_code = core_proc.returncode
    elif gui_proc_holder[0] is not None and gui_proc_holder[0].returncode:
        exit_code = gui_proc_holder[0].returncode
    sys.exit(exit_code)


if __name__ == '__main__':
    main()

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


def _terminate_process(proc: subprocess.Popen[bytes]) -> None:
    """Send SIGTERM and wait briefly, then SIGKILL if still alive."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _spawn_core(core_exe: Path) -> subprocess.Popen[bytes]:
    """Spawn the ubo-core process."""
    return subprocess.Popen([str(core_exe)])  # noqa: S603


def _spawn_gui(
    gui_exe: Path,
    host: str,
    port: int,
) -> subprocess.Popen[bytes]:
    """Spawn the ubo-gui-client process."""
    return subprocess.Popen(  # noqa: S603
        [str(gui_exe), '--host', host, '--port', str(port)],
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
) -> None:
    """Block until either child process exits."""
    while core_proc.poll() is None and gui_proc.poll() is None:
        time.sleep(0.5)

    if core_proc.poll() is not None:
        logger.info('ubo-core exited with code %d', core_proc.returncode)
    if gui_proc.poll() is not None:
        logger.info('ubo-gui-client exited with code %d', gui_proc.returncode)


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

    # Signal forwarding
    children: list[subprocess.Popen[bytes]] = [core_proc]

    def _forward_signal(signum: int, _frame: object) -> None:
        for child in children:
            if child.poll() is None:
                child.send_signal(signum)

    signal.signal(signal.SIGTERM, _forward_signal)
    signal.signal(signal.SIGINT, _forward_signal)

    gui_proc: subprocess.Popen[bytes] | None = None

    try:
        if headless_only:
            core_proc.wait()
            return

        _wait_for_core_grpc(core_proc, _GRPC_HOST, _GRPC_PORT)

        gui_proc = _spawn_gui(gui_exe, _GRPC_HOST, _GRPC_PORT)
        children.append(gui_proc)

        _monitor_children(core_proc, gui_proc)

    finally:
        if gui_proc is not None:
            _terminate_process(gui_proc)
        _terminate_process(core_proc)

    exit_code = 0
    if core_proc.returncode:
        exit_code = core_proc.returncode
    elif gui_proc is not None and gui_proc.returncode:
        exit_code = gui_proc.returncode
    sys.exit(exit_code)


if __name__ == '__main__':
    main()

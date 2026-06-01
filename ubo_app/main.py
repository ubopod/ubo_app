"""Process supervisor that spawns ubo-core and ubo-gui-client as children."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger('ubo_supervisor')
logging.basicConfig(level=logging.INFO)

# Default gRPC connection parameters (same env vars as constants/__init__.py)
_GRPC_HOST = os.environ.get('UBO_GRPC_LISTEN_ADDRESS', '127.0.0.1')
_GRPC_PORT = int(os.environ.get('UBO_GRPC_LISTEN_PORT', '50051'))

# GUI backend: 'kivy' (default) spawns ubo-gui-client; 'lvgl' spawns the LVGL
# client (ubo-lvgl-gui-client) with the display backend from UBO_LVGL_BACKEND
# ('st7789' on the device, 'sdl' on desktop).
_GUI_BACKEND = os.environ.get('UBO_GUI_BACKEND', 'kivy').lower()
_LVGL_DISPLAY = os.environ.get('UBO_LVGL_BACKEND', 'st7789')


def _gui_spec() -> tuple[str, tuple[str, ...]]:
    """Return (executable name, extra args) for the selected GUI backend."""
    if _GUI_BACKEND == 'lvgl':
        return 'ubo-lvgl-gui-client', ('--backend', _LVGL_DISPLAY)
    return 'ubo-gui-client', ()

_CORE_SHUTDOWN_TIMEOUT = 30.0  # max seconds to wait for core graceful shutdown


def _find_executable(name: str) -> Path | None:
    """Find an executable in the venv or the GUI subpackage's venv."""
    # Prefer the GUI client's isolated venv at INSTALLATION_PATH/gui-client/bin/
    installation_path = os.environ.get('UBO_INSTALLATION_PATH', '/opt/ubo')
    gui_installed = Path(installation_path) / 'gui-client' / 'bin' / name
    if gui_installed.is_file() and os.access(gui_installed, os.X_OK):
        return gui_installed

    # Then check the main venv bin directory
    bin_dir = Path(sys.executable).parent
    candidate = bin_dir / name
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate

    # Fallback: check the GUI subpackage's dev venv (ubo_app/gui/.venv/bin/)
    gui_venv = Path(__file__).parent / 'gui' / '.venv' / 'bin' / name
    if gui_venv.is_file() and os.access(gui_venv, os.X_OK):
        return gui_venv

    return None


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
    extra_args: tuple[str, ...] = (),
) -> subprocess.Popen[bytes]:
    """Spawn the GUI client process in its own session."""
    return subprocess.Popen(  # noqa: S603
        [str(gui_exe), *extra_args, '--host', host, '--port', str(port)],
        start_new_session=True,
    )


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
                'GUI client exited unexpectedly with code %d',
                gui_proc.returncode,
            )
            return
        time.sleep(0.5)

    logger.info('ubo-core exited with code %d', core_proc.returncode)


def _kill_process_group(proc: subprocess.Popen[bytes]) -> None:
    """Send SIGKILL to the entire process group of a child."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def _install_signal_handlers(
    core_proc: subprocess.Popen[bytes],
    gui_proc_holder: list[subprocess.Popen[bytes] | None],
    shutting_down: list[bool],
) -> None:
    """Install SIGINT/SIGTERM handlers for ordered child shutdown."""

    def _handle_sigint(_signum: int, _frame: object) -> None:
        if shutting_down[0]:
            logger.warning('Second interrupt received, killing children')
            _kill_process_group(core_proc)
            if gui_proc_holder[0] is not None:
                _kill_process_group(gui_proc_holder[0])
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

    gui_name, gui_extra_args = _gui_spec()
    logger.info('GUI backend: %s (%s)', _GUI_BACKEND, gui_name)
    gui_exe = _find_executable(gui_name)
    headless_only = gui_exe is None
    if headless_only:
        logger.warning('%s not found, running headless only', gui_name)

    shutting_down: list[bool] = [False]
    gui_proc_holder: list[subprocess.Popen[bytes] | None] = [None]

    # Spawn GUI first so its window starts initializing (showing splash)
    # while core boots up
    if not headless_only:
        gui_proc_holder[0] = _spawn_gui(
            gui_exe, _GRPC_HOST, _GRPC_PORT, gui_extra_args,
        )

    core_proc = _spawn_core(core_exe)

    _install_signal_handlers(core_proc, gui_proc_holder, shutting_down)

    try:
        if headless_only:
            core_proc.wait()
            return

        gui_proc = gui_proc_holder[0]
        if gui_proc is None:  # unreachable: headless_only check above
            return
        _monitor_children(core_proc, gui_proc, shutting_down)

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

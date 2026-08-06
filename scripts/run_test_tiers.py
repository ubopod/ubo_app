"""Run the unit and app test tiers as separate pytest processes.

Two invocations on purpose: `app_context` tests wipe `sys.modules` between
tests (tests/fixtures/app.py), which poisons unit-tier modules collected in
the same process — isinstance/except checks silently miss against re-imported
classes. Process separation makes that impossible.

Extra command-line arguments (e.g. `--override-store-snapshots`) are
forwarded to both tiers. Both tiers always run; the exit code is non-zero if
either failed, so a full run reports every failure the way a single pytest
invocation would.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import pty
import struct
import subprocess
import sys
import termios
import traceback
from pathlib import Path

# Written incrementally (one tier's verdict appended as soon as it finishes),
# so results survive both a huge run scrolling past the terminal's buffer and
# a later tier hanging or crashing before the in-terminal recap ever prints.
# Bind-mounted into the Docker test container, so it lands on the host too.
RECAP_LOG_PATH = Path(__file__).resolve().parent.parent / 'test-tiers-recap.log'

TIERS = {
    'unit': [
        'tests/store',
        'tests/navigation',
        'tests/gui',
        'tests/grpc',
        'tests/utils',
        '--ignore=tests/store/test_subscribe_event.py',
    ],
    'app': [
        'tests/flows',
        'tests/integration',
        'tests/reproduction',
        'tests/store/test_subscribe_event.py',
    ],
}

# Fallback tail length (in lines) when a tier crashes before printing its own
# pytest "short test summary info" section (e.g. a collection error).
_FALLBACK_TAIL_LINES = 15
_PTY_READ_CHUNK = 4096


def _pty_window_size() -> bytes:
    """Pack the real terminal's rows/cols for TIOCSWINSZ, falling back to 80x24."""
    try:
        columns, rows = os.get_terminal_size(sys.stdout.fileno())
    except OSError:
        columns, rows = 80, 24
    return struct.pack('HHHH', rows, columns, 0, 0)


def _run_tier(tier: list[str]) -> tuple[int, str]:
    """Run one tier in a pty, streaming its output live and capturing its tail.

    Pytest's interactive dot/percentage reporter depends on ``isatty()``
    being true on its stdout; a plain ``subprocess.PIPE`` fails that check and
    silently switches pytest to a plainer, differently-buffered reporter. A
    pty keeps pytest's own terminal detection intact, so the live output
    looks exactly like running it directly in a terminal.

    The tail (the tier's own "short test summary info" section, or its last
    lines if that marker never printed) is returned so a failing tier's
    result can be reprinted in the recap — otherwise a noisier later tier
    scrolls it off-screen before the run finishes.
    """
    controller_fd, subordinate_fd = pty.openpty()
    with contextlib.suppress(OSError):
        fcntl.ioctl(subordinate_fd, termios.TIOCSWINSZ, _pty_window_size())

    process = subprocess.Popen(  # noqa: S603
        [sys.executable, '-m', 'pytest', *tier, *sys.argv[1:]],
        stdin=subordinate_fd,
        stdout=subordinate_fd,
        stderr=subordinate_fd,
        env={**os.environ, 'PYTHONUNBUFFERED': '1'},
    )
    os.close(subordinate_fd)

    chunks: list[str] = []
    while True:
        try:
            data = os.read(controller_fd, _PTY_READ_CHUNK)
        except OSError as error:
            if error.errno == errno.EIO:
                break  # Child closed its end of the pty — normal pty EOF.
            raise
        if not data:
            break
        text = data.decode('utf-8', errors='replace')
        sys.stdout.write(text)
        sys.stdout.flush()
        chunks.append(text)
    os.close(controller_fd)
    process.wait()

    output = ''.join(chunks)
    summary_start = output.rfind('short test summary info')
    if summary_start == -1:
        tail = '\n'.join(output.splitlines()[-_FALLBACK_TAIL_LINES:])
    else:
        line_start = output.rfind('\n', 0, summary_start) + 1
        tail = output[line_start:]
    return process.returncode, tail


def _format_tier_result(name: str, tier: list[str], code: int, tail: str) -> str:
    verdict = 'passed' if code == 0 else f'FAILED (exit {code})'
    text = f'{name} tier ({" ".join(tier[:1])} ...): {verdict}\n'
    if code != 0 and tail:
        text += tail
    return text


def main() -> int:
    """Run both tiers, forwarding extra arguments to each.

    A failing tier's summary can scroll off-screen behind a later, noisier
    tier, so the consolidated recap below reprints every tier's result
    together at the very end. Each tier's result is *also* appended to
    ``RECAP_LOG_PATH`` as soon as that tier finishes (not just printed at the
    end), so it survives a later tier hanging or crashing outright, or the
    whole run scrolling past the terminal's buffer. A tier that raises before
    pytest itself could report anything is still recorded as a failure rather
    than silently dropping that tier's result (and the other tier's chance to
    run).
    """
    RECAP_LOG_PATH.write_text('')
    results: dict[str, int] = {}
    tier_reports: dict[str, str] = {}
    for name, tier in TIERS.items():
        try:
            code, tail = _run_tier(tier)
        except Exception:  # noqa: BLE001 -- one tier crashing must not hide the rest
            code = 1
            tail = f'Tier crashed before pytest could report:\n{traceback.format_exc()}'
        results[name] = code
        tier_reports[name] = _format_tier_result(name, tier, code, tail)
        with RECAP_LOG_PATH.open('a') as log_file:
            log_file.write(tier_reports[name])

    recap = '\n================= test tiers recap =================\n'
    recap += ''.join(tier_reports.values())
    overall = next((code for code in results.values() if code), 0)
    recap += (
        'overall: all tiers passed\n'
        if overall == 0
        else 'overall: FAILED — scroll up to the failing tier for details\n'
    )
    recap += f'Full per-tier results also written to {RECAP_LOG_PATH}\n'
    sys.stdout.write(recap)
    sys.stdout.flush()
    with RECAP_LOG_PATH.open('a') as log_file:
        log_file.write(recap)
    return overall


if __name__ == '__main__':
    sys.exit(main())

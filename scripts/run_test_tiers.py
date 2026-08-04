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

import subprocess
import sys

UNIT_TIER = [
    'tests/store',
    'tests/navigation',
    'tests/gui',
    'tests/grpc',
    'tests/utils',
    '--ignore=tests/store/test_subscribe_event.py',
]
APP_TIER = [
    'tests/flows',
    'tests/integration',
    'tests/reproduction',
    'tests/store/test_subscribe_event.py',
]


def main() -> int:
    """Run both tiers, forwarding extra arguments to each."""
    exit_code = 0
    for tier in (UNIT_TIER, APP_TIER):
        result = subprocess.run(  # noqa: S603
            [sys.executable, '-m', 'pytest', *tier, *sys.argv[1:]],
            check=False,
        )
        exit_code = exit_code or result.returncode
    return exit_code


if __name__ == '__main__':
    sys.exit(main())

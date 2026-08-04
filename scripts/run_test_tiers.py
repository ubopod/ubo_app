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


def main() -> int:
    """Run both tiers, forwarding extra arguments to each.

    Each tier prints its own pytest summary, so the last summary on screen
    covers only the app tier — the recap below is the whole run's verdict.
    """
    results: dict[str, int] = {}
    for name, tier in TIERS.items():
        results[name] = subprocess.run(  # noqa: S603
            [sys.executable, '-m', 'pytest', *tier, *sys.argv[1:]],
            check=False,
        ).returncode

    sys.stdout.write('\n================= test tiers recap =================\n')
    for name, code in results.items():
        verdict = 'passed' if code == 0 else f'FAILED (exit {code})'
        sys.stdout.write(f'{name} tier ({" ".join(TIERS[name][:1])} ...): {verdict}\n')
    overall = next((code for code in results.values() if code), 0)
    sys.stdout.write(
        'overall: all tiers passed\n'
        if overall == 0
        else 'overall: FAILED — scroll up to the failing tier for details\n',
    )
    sys.stdout.flush()
    return overall


if __name__ == '__main__':
    sys.exit(main())

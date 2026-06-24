"""Pytest fixtures shared across the assistant subprocess tests."""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest
from provider_harness import SECRET_ID_ENV, FakeUboRPCClient

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope='session', autouse=True)
def _export_secret_id_env() -> Iterator[None]:
    """Export the ``<NAME>_SECRET_ID`` env vars request_providers._secret reads.

    Production sets these via ``ubo_handle.binary_env_provider``; tests aren't
    launched through that path, so mirror the mapping here for the session.
    """
    saved = {name: os.environ.get(name) for name in SECRET_ID_ENV}
    os.environ.update(SECRET_ID_ENV)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture(autouse=True)
def _short_request_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bound each provider request to ~15s.

    A healthy provider returns its first frame quickly, but a cold websocket
    TTS/STT (ElevenLabs, Rime, …) can take >10s to hand back its first frame on
    the opening connection. 15s gives them margin while still failing reasonably
    fast on a provider the one-shot genuinely can't drive (vs the production
    45s/15s defaults).
    """
    monkeypatch.setenv('UBO_ASSISTANT_FIRST_OUTPUT_TIMEOUT_SECS', '15')
    monkeypatch.setenv('UBO_ASSISTANT_STT_FLUSH_TIMEOUT_SECS', '15')
    monkeypatch.setenv('UBO_ASSISTANT_RUN_TASK_BACKSTOP_SECS', '20')
    monkeypatch.setenv('UBO_ASSISTANT_CANCEL_GRACE_SECS', '2')


@pytest.fixture
def client() -> FakeUboRPCClient:
    """Return a fresh fake RPC client (real secrets, captured output) per test."""
    return FakeUboRPCClient()


# Teardown watchdog — ONLY for sessions that include `providers` tests, i.e. the
# manual ``poe test:providers`` run (the default ``poe test`` is ``-m "not
# providers"`` and never arms this, so a teardown hang in the unit suite — or in
# CI — still surfaces normally). Those provider sessions spawn pipecat websocket
# services (ElevenLabs/Rime TTS) that leave a task/thread ignoring cancellation
# during cleanup, hanging the event-loop/session teardown *after* all results are
# reported; a hookwrapper can't help (the hang is inside the test loop's own
# teardown). Once every test body has finished, arm a short daemon watchdog: a
# clean teardown exits before it fires; a wedged one is force-exited with the real
# test status and a loud stderr warning (so the hang is reported, not silent).
# Trading exit status for "tests passed but teardown leaked" is acceptable here
# because this only runs by hand against real providers.
_WATCHDOG_GRACE_SECS = 5.0
_watchdog: dict[str, int | bool] = {
    'total': 0,
    'done': 0,
    'failed': False,
    'armed': False,
    'has_providers': False,
}


def pytest_collection_finish(session: pytest.Session) -> None:
    """Record the run size and whether any `providers` test is in the session."""
    _watchdog['total'] = len(session.items)
    _watchdog['has_providers'] = any(
        item.get_closest_marker('providers') is not None for item in session.items
    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Arm the teardown watchdog once every test body has finished."""
    if report.failed:
        _watchdog['failed'] = True
    finished = report.when == 'call' or (
        report.when == 'setup' and (report.skipped or report.failed)
    )
    if finished:
        _watchdog['done'] = int(_watchdog['done']) + 1
    if (
        _watchdog['has_providers']
        and not _watchdog['armed']
        and _watchdog['total']
        and int(_watchdog['done']) >= int(_watchdog['total'])
    ):
        _watchdog['armed'] = True

        def _force_exit() -> None:
            time.sleep(_WATCHDOG_GRACE_SECS)
            if sys.is_finalizing():
                return  # interpreter already shutting down cleanly; let it
            print(  # noqa: T201
                '\n[provider-watchdog] teardown did not finish within '
                f'{_WATCHDOG_GRACE_SECS:.0f}s of the last test (leaked websocket '
                'task); forcing exit with the test status.',
                file=sys.stderr,
                flush=True,
            )
            os._exit(1 if _watchdog['failed'] else 0)

        threading.Thread(target=_force_exit, daemon=True).start()

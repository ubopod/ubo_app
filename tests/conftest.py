"""Pytest configuration file for the tests."""

from __future__ import annotations

import json
import subprocess
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import dotenv
import pytest

if TYPE_CHECKING:
    from _pytest.fixtures import SubRequest

    from ubo_app.store.main import RootState

dotenv.load_dotenv(Path(__file__).parent / '.dev.env')
dotenv.load_dotenv(Path(__file__).parent / '.env')

# Redirect the persistent store to a throwaway location BEFORE any ubo_app
# store module is imported. Several ``Immutable`` state classes call
# ``read_from_persistent_store()`` at class-definition time to seed field
# defaults; without this redirect those defaults would be read from — and
# the test suite would later write to — the developer's real
# ``~/Library/Application Support/ubo/state.json``. The throwaway file is
# intentionally absent so the reads fall through to the true code defaults,
# keeping ``reducer(None, InitAction())`` deterministic across machines.
# The per-test ``_persistent_store`` fixture monkey-patches this again to a
# per-test ``tmp_path`` for write isolation; monkeypatch then reverts to
# this session path (never the production one).
import tempfile as _tempfile  # noqa: E402

import ubo_app.constants as _ubo_constants  # noqa: E402
import ubo_app.utils.persistent_store as _ubo_persistent_store  # noqa: E402

_SESSION_STATE_PATH = Path(_tempfile.mkdtemp()) / 'state.json'
_ubo_constants.PERSISTENT_STORE_PATH = _SESSION_STATE_PATH
_ubo_persistent_store.PERSISTENT_STORE_PATH = _SESSION_STATE_PATH

pytest.register_assert_rewrite('tests.fixtures')

from tests.fixtures import (  # noqa: E402, I001
    AppContext,
    Dispatcher,
    LoadServices,
    MockCamera,
    Stability,
    WaitForEmptyMenu,
    WindowSnapshot,
    app_context,
    camera,
    dispatcher,
    load_services,
    mock_environment,
    snapshot_prefix,
    stability,
    store,
    wait_for_empty_menu,
    wait_for_menu_item,
    window_snapshot,
)
from redux_pytest.fixtures import (  # noqa: E402
    StoreMonitor,
    Waiter,
    WaitFor,
    store_monitor,
    store_snapshot,
    wait_for,
)


def exclude_dynamic_menus(state: RootState) -> dict[str, Any]:
    """Exclude dynamic_menus from store snapshots."""
    return {
        f.name: getattr(state, f.name)
        for f in fields(state)
        if f.name != 'dynamic_menus'
    }


fixtures = (
    AppContext,
    Dispatcher,
    LoadServices,
    MockCamera,
    Stability,
    Waiter,
    WaitFor,
    WaitForEmptyMenu,
    WindowSnapshot,
    StoreMonitor,
    app_context,
    dispatcher,
    load_services,
    camera,
    mock_environment,
    snapshot_prefix,
    stability,
    store,
    store_monitor,
    store_snapshot,
    wait_for,
    wait_for_empty_menu,
    wait_for_menu_item,
    window_snapshot,
)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add options to the pytest command line."""
    parser.addoption('--use-fakefs', action='store_true')
    # --override-window-snapshots and --make-screenshots are registered by
    # headless_kivy_pytest plugin. If it's not installed, register them here.
    try:
        import headless_kivy_pytest.plugin  # noqa: F401
    except ImportError:
        parser.addoption('--override-window-snapshots', action='store_true')
        parser.addoption('--make-screenshots', action='store_true')


@pytest.fixture(autouse=True)
def _persistent_store(
    request: SubRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set defaults for app-context for tests.

    Crucially, this redirects ``PERSISTENT_STORE_PATH`` to a per-test
    ``tmp_path`` so the test suite never writes to the production
    ``~/Library/Application Support/ubo/state.json`` (or the equivalent
    on other platforms). Without this, running the test suite on the
    same machine that runs the real app would silently wipe the user's
    persisted settings on every test.
    """
    persistent_store_marker = request.node.get_closest_marker('persistent_store')
    persistent_store_data = {
        'wifi_has_visited_onboarding': True,
        # All wake-word slots disabled so recognition is off by default in tests
        # (stored as the JSON-string blob the app itself persists).
        'speech_recognition:wake_slots': json.dumps(
            [
                {'mode': mode, 'phrases': [phrase], 'enabled': False}
                for mode, phrase in (
                    ('intents', 'short voice command'),
                    ('quick_chat', 'hey quick question'),
                    ('conversation', "let's have a conversation"),
                    ('stop_talking', 'okay enough'),
                )
            ],
        ),
    }
    if persistent_store_marker:
        persistent_store_data = {
            **persistent_store_data,
            **persistent_store_marker.args[0],
        }

    test_state_path = tmp_path / 'state.json'
    # ``register_persistent_store`` reads ``PERSISTENT_STORE_PATH`` from
    # ``ubo_app.constants`` at call time; ``read_from_persistent_store``
    # references the alias bound in ``ubo_app.utils.persistent_store`` at
    # module import. Both need redirecting so the autorun write path and
    # the dataclass-default read path land on the isolated tmp file.
    import ubo_app.constants
    import ubo_app.utils.persistent_store

    monkeypatch.setattr(ubo_app.constants, 'PERSISTENT_STORE_PATH', test_state_path)
    monkeypatch.setattr(
        ubo_app.utils.persistent_store,
        'PERSISTENT_STORE_PATH',
        test_state_path,
    )

    test_state_path.parent.mkdir(parents=True, exist_ok=True)
    test_state_path.write_text(json.dumps(persistent_store_data))


@pytest.fixture(autouse=True)
def _logger() -> None:
    import logging

    from ubo_app.logger import ExtraFormatter

    extra_formatter = ExtraFormatter()

    for handler in logging.getLogger().handlers:
        if handler.formatter:
            handler.formatter.format = extra_formatter.format
            cast(
                'ExtraFormatter',
                handler.formatter,
            ).def_keys = extra_formatter.def_keys


@pytest.fixture(autouse=True)
def _setup_script(request: pytest.FixtureRequest) -> None:
    """Run the setup script for the test."""
    # Get the directory of the test file that invoked the fixture
    test_dir = request.path.parent
    current_dir = Path().absolute()

    while test_dir != current_dir.parent:
        script_path = test_dir / 'setup.sh'

        if script_path.exists():
            # Running the setup script
            subprocess.run(['/usr/bin/env', 'bash', script_path], check=True)  # noqa: S603

        test_dir = test_dir.parent


_ = fixtures, _logger, _setup_script


_exit_status = 0


def pytest_sessionfinish(
    session: pytest.Session,  # noqa: ARG001
    exitstatus: int,
) -> None:
    """Capture exit status for use in pytest_unconfigure."""
    global _exit_status  # noqa: PLW0603
    _exit_status = exitstatus


def pytest_unconfigure(config: pytest.Config) -> None:  # noqa: ARG001
    """Force-stop dangling threads after pytest has printed all output."""
    import sys
    import threading

    if 'ubo_app.store.main' in sys.modules:
        from ubo_app.store.main import scheduler

        scheduler.stop()
        scheduler.join(timeout=5)

    alive = [
        t
        for t in threading.enumerate()
        if t is not threading.main_thread() and not t.daemon
    ]
    if alive:
        import os

        os._exit(_exit_status)

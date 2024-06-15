"""Pytest configuration file for the tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

import dotenv
import pytest

from tests.monkeypatch import _monkeypatch

dotenv.load_dotenv(Path(__file__).parent / '.env')

pytest.register_assert_rewrite('tests.fixtures')

from tests.fixtures import (  # noqa: E402, I001
    AppContext,
    LoadServices,
    MockCamera,
    Stability,
    WindowSnapshot,
    app_context as original_app_context,
    load_services,
    camera,
    stability,
    store,
    window_snapshot,
)

from redux_pytest.fixtures import (  # noqa: E402
    StoreMonitor,
    Waiter,
    WaitFor,
    needs_finish,
    store_monitor,
    store_snapshot,
    wait_for,
)

fixtures = (
    AppContext,
    LoadServices,
    MockCamera,
    Stability,
    Waiter,
    WaitFor,
    WindowSnapshot,
    StoreMonitor,
    original_app_context,
    load_services,
    camera,
    needs_finish,
    stability,
    store,
    store_monitor,
    store_snapshot,
    wait_for,
    window_snapshot,
)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add options to the pytest command line."""
    parser.addoption('--override-window-snapshots', action='store_true')
    parser.addoption('--make-screenshots', action='store_true')
    parser.addoption('--use-fake-filesystem', action='store_true')


@pytest.fixture(autouse=True)
def app_context(original_app_context: AppContext) -> AppContext:
    """Set defaults for app-context for tests."""
    original_app_context.set_persistent_storage_value(
        'wifi_has_visited_onboarding',
        value=True,
    )
    return original_app_context


@pytest.fixture(autouse=True)
def _logger() -> None:
    import logging

    from ubo_app.logging import ExtraFormatter

    extra_formatter = ExtraFormatter()

    for handler in logging.getLogger().handlers:
        if handler.formatter:
            handler.formatter.format = extra_formatter.format
            cast(ExtraFormatter, handler.formatter).def_keys = extra_formatter.def_keys

    import time

    time.sleep(5)


@pytest.fixture(autouse=True)
def _setup_script(request: pytest.FixtureRequest) -> None:
    """Run the setup script for the test."""
    # Get the directory of the test file that invoked the fixture
    test_dir = request.path.parent

    script_path = test_dir / 'setup.sh'

    if not script_path.exists():
        return

    # Running the setup script
    subprocess.run(['/usr/bin/env', 'bash', script_path], check=True)  # noqa: S603


_ = fixtures, _logger, _monkeypatch, _setup_script

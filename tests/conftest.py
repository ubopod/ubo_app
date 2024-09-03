"""Pytest configuration file for the tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

import dotenv
import pytest

dotenv.load_dotenv(Path(__file__).parent / '.env')

pytest.register_assert_rewrite('tests.fixtures')

from tests.fixtures import (  # noqa: E402, I001
    AppContext,
    LoadServices,
    MockCamera,
    Stability,
    WaitForEmptyMenu,
    app_context as original_app_context,
    camera,
    load_services,
    mock_environment,
    stability,
    store,
    wait_for_empty_menu,
    wait_for_menu_item,
)
from headless_kivy_pytest.fixtures import WindowSnapshot, window_snapshot  # noqa: E402
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
    WaitForEmptyMenu,
    WindowSnapshot,
    StoreMonitor,
    original_app_context,
    load_services,
    camera,
    mock_environment,
    needs_finish,
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
    parser.addoption('--override-window-snapshots', action='store_true')
    parser.addoption('--make-screenshots', action='store_true')
    parser.addoption('--use-fakefs', action='store_true')


@pytest.fixture
def snapshot_prefix() -> str:
    """Return the prefix for the snapshots."""
    from ubo_app.utils import IS_RPI

    if IS_RPI:
        return 'rpi'

    return 'desktop'


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

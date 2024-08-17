"""Pytest configuration file for flow tests."""

from pathlib import Path

import pytest

FLOW_TIMEOUT = 150


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Modify the collection of items and set their timeout."""
    _ = config
    current_dir = Path(__file__).parent.absolute().as_posix()
    for item in items:
        test_module = Path(item.fspath).absolute().as_posix()
        if test_module.startswith(current_dir):
            item.add_marker(pytest.mark.timeout(FLOW_TIMEOUT))

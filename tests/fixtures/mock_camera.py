"""Store tests fixtures."""

from __future__ import annotations

import os
import shutil

import pytest


class MockCamera:
    """Mock camera for testing."""

    def set_image(self: MockCamera, image_name: str) -> None:
        """Set the image to be taken."""
        shutil.copyfile(
            f'{os.environ["TEST_ROOT_PATH"]}/tests/data/{image_name}.png',
            '/tmp/qrcode_input.png',  # noqa: S108
        )


@pytest.fixture
def camera() -> MockCamera:
    """Camera mocking tools."""
    return MockCamera()

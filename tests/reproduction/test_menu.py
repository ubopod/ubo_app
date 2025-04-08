"""Test navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ubo_app.constants import CORE_SERVICE_IDS, TEST_INVESTIGATION_MODE
from ubo_app.logger import logger

if TYPE_CHECKING:
    from tests.fixtures.app import AppContext
    from tests.fixtures.load_services import LoadServices
    from tests.fixtures.stability import Stability

SCREEN_DIFFERENCE_THRESHOLD = 0.01

# Debug mode is enabled to reproduce issues happening rarely in production by running
# the test multiple times until the issue is reproduced.
INVESTIGATION_MODE_TIMEOUT = 1000000


@(
    pytest.mark.timeout(INVESTIGATION_MODE_TIMEOUT)
    if TEST_INVESTIGATION_MODE
    else lambda f: f
)
@pytest.mark.repeat(1000 if TEST_INVESTIGATION_MODE else 1)
async def test_root_menu_bad_state(
    app_context: AppContext,
    stability: Stability,
    load_services: LoadServices,
) -> None:
    """Test navigation."""
    from ubo_app.store.core.types import MenuChooseByIconAction
    from ubo_app.store.main import store

    app_context.set_app()

    logger.info('Loading services')
    unload_waiter = await load_services(
        CORE_SERVICE_IDS,
        timeout=40,
        gap_duration=0.4,
        run_async=True,
    )
    logger.info('Services loaded, waiting for stability')
    await stability(attempts=2, wait=2)

    logger.info('Navigating to the first menu item')
    store.dispatch(MenuChooseByIconAction(icon='󰍜'))

    logger.info('Waiting for stability')
    await stability()

    from headless_kivy import HeadlessWidget

    if abs(HeadlessWidget.raw_data.mean() - 127.96) > SCREEN_DIFFERENCE_THRESHOLD:
        logger.info(
            'Not the expected screen',
            extra={
                'mean': HeadlessWidget.raw_data.mean(),
                'expected': 127.96,
            },
        )
        if TEST_INVESTIGATION_MODE:
            import ipdb  # noqa: T100

            ipdb.set_trace()  # noqa: T100

    logger.info('Waiting for the services to unload')
    await unload_waiter(timeout=40)

    logger.info('Test complete')

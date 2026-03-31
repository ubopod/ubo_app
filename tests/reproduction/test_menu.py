"""Test navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fake import Fake

from ubo_app.constants import CORE_SERVICE_IDS, TEST_INVESTIGATION_MODE
from ubo_app.logger import logger

if TYPE_CHECKING:
    from tests.fixtures.app import AppContext
    from tests.fixtures.load_services import LoadServices
    from tests.fixtures.stability import Stability

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
    monkeypatch: pytest.MonkeyPatch,
    app_context: AppContext,
    stability: Stability,
    load_services: LoadServices,
) -> None:
    """Test navigation."""
    import asyncio

    monkeypatch.setattr(asyncio.subprocess, 'create_subprocess_exec', Fake())

    from ubo_app.store.core.types import MenuChooseByIconAction
    from ubo_app.store.main import store

    app_context.set_app()

    logger.info('Loading services')
    unload_waiter = await load_services(
        CORE_SERVICE_IDS,
        timeout=90,
        run_async=True,
    )
    logger.info('Services loaded, waiting for stability')
    await stability(initial_wait=6)

    logger.info('Navigating to the first menu item')
    store.dispatch(MenuChooseByIconAction(icon='󰍜'))

    logger.info('Waiting for stability')
    await stability(initial_wait=3, attempts=3, wait=2)

    # Verify that the current view has changed (navigated to a sub-menu)
    from ubo_app.store.core.types import MenuViewData

    state = store._state  # noqa: SLF001
    current_view = state.main.current_view if state else None
    if not isinstance(current_view, MenuViewData) or current_view.title is None:
        if TEST_INVESTIGATION_MODE:
            logger.info(
                'Not the expected screen - current view is not a menu',
                extra={'current_view': type(current_view).__name__},
            )
            import ipdb  # noqa: T100

            ipdb.set_trace()  # noqa: T100
        assert isinstance(current_view, MenuViewData), (
            f'Expected MenuViewData after navigation, got {type(current_view).__name__}'
        )
        assert current_view.title is not None, (
            'MenuViewData.title is None — navigation did not reach a sub-menu'
        )

    logger.info('Waiting for the services to unload')
    await unload_waiter(timeout=40)

    logger.info('Test complete')

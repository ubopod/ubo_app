"""Test navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fake import Fake

from ubo_app.constants import CORE_SERVICE_IDS, TEST_INVESTIGATION_MODE
from ubo_app.logger import logger

if TYPE_CHECKING:
    from redux_pytest.fixtures import WaitFor

    from tests.fixtures.app import AppContext
    from tests.fixtures.load_services import LoadServices

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
    load_services: LoadServices,
    wait_for: WaitFor,
) -> None:
    """Test navigation."""
    import asyncio

    monkeypatch.setattr(asyncio.subprocess, 'create_subprocess_exec', Fake())

    from tenacity import RetryError, stop_after_delay, wait_fixed

    from ubo_app.store.core.types import (
        HomeViewData,
        MenuChooseByIconAction,
        MenuViewData,
    )
    from ubo_app.store.main import store

    app_context.set_app()

    logger.info('Loading services')
    unload_waiter = await load_services(
        CORE_SERVICE_IDS,
        timeout=90,
        run_async=True,
    )

    # Wait for the home view before navigating — the navigation reads the home
    # items to resolve the chosen icon. This polls for the outcome rather than
    # using ``stability``: the rewritten ``stability`` early-exits as soon as the
    # screen stops changing, which is trivially satisfied by the pre-navigation
    # home view before the async navigation chain has run.
    logger.info('Services loaded, waiting for the home view')

    @wait_for(run_async=True, wait=wait_fixed(0.5), stop=stop_after_delay(90))
    def home_is_ready() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        current_view = state.main.current_view
        assert isinstance(current_view, HomeViewData), (
            f'expected home view, got {type(current_view).__name__}'
        )
        assert current_view.menu_items, 'home view has no menu items yet'

    await home_is_ready()

    logger.info('Navigating to the first menu item')
    store.dispatch(MenuChooseByIconAction(icon='󰍜'))

    # Wait for the navigation *outcome* — a menu view. The timeout is generous:
    # under a full-service load the Redux action queue can be flooded (notably by
    # the always-on audio mic-sample stream), so the navigation chain's actions
    # and events drain slowly and the menu can take a while to appear.
    logger.info('Waiting for the navigation to reach the main menu')

    @wait_for(run_async=True, wait=wait_fixed(0.5), stop=stop_after_delay(120))
    def navigated_to_menu() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        current_view = state.main.current_view
        assert isinstance(current_view, MenuViewData), (
            f'Expected MenuViewData after navigation, got {type(current_view).__name__}'
        )
        assert current_view.title is not None, (
            'MenuViewData.title is None — navigation did not reach a sub-menu'
        )

    try:
        await navigated_to_menu()
    except RetryError as error:
        if TEST_INVESTIGATION_MODE:
            logger.info('Not the expected screen - current view is not a menu')
            import ipdb  # noqa: T100

            ipdb.set_trace()  # noqa: T100
        # Surface the underlying assertion message instead of the RetryError.
        underlying = error.last_attempt.exception()
        if isinstance(underlying, AssertionError):
            raise underlying from error
        raise

    logger.info('Waiting for the services to unload')
    await unload_waiter(timeout=40)

    logger.info('Test complete')

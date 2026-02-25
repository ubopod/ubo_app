"""Sets up the display for the Raspberry Pi and manages its state."""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from ubo_app.display import display
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import register_path_menu_matcher
from ubo_app.store.main import store
from ubo_app.store.services.display import (
    DisplayBlankAction,
    DisplayBlankEvent,
    DisplayBlankTimeout,
    DisplaySetBlankTimeoutAction,
    DisplayState,
    DisplayUnblankEvent,
    DisplayUpdateActivityAction,
)
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils import IS_TEST_ENV
from ubo_app.utils.menu_items import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
)
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_gui.menu.types import Item

    from ubo_app.utils.types import Subscriptions

splash_screen = None

# Event to signal when the display is unblanked
# Python 3.10+ allows creation without running loop
_unblank_event = asyncio.Event()


async def monitor_inactivity() -> None:
    """Monitor user inactivity and blank screen after timeout."""
    logger.verbose('=== MONITOR INACTIVITY TASK STARTED ===')

    try:
        while True:
            # Get current display state using with_state
            @store.with_state(
                lambda state: (
                    state.display if hasattr(state, 'display') else None
                ),
            )
            def get_display_state(
                display_state: DisplayState | None,
            ) -> DisplayState | None:
                return display_state

            display_state = get_display_state()

            if display_state is None:
                logger.warning('Display state not available')
                await asyncio.sleep(10)
                continue

            # If display is already blanked, wait for unblank event instead of polling
            if display_state.is_blanked:
                logger.verbose(
                    'Display is blanked, waiting for unblank event',
                )
                _unblank_event.clear()
                await _unblank_event.wait()
                logger.verbose('Display unblanked, resuming inactivity monitoring')
                continue

            # Skip blanking if timeout is OFF
            timeout_seconds = display_state.selected_blank_timeout.get_timeout_seconds()
            if timeout_seconds is None:
                await asyncio.sleep(10)
                continue

            current_time = datetime.datetime.now(tz=datetime.UTC).timestamp()
            logger.verbose(
                'Inactivity check',
                extra={
                    'last_activity': display_state.last_activity_time,
                    'blank_timeout': timeout_seconds,
                    'is_blanked': display_state.is_blanked,
                    'current_time': current_time,
                },
            )

            if display_state.last_activity_time is not None:
                inactive_duration = current_time - display_state.last_activity_time
                logger.verbose(
                    'Checking inactivity duration',
                    extra={
                        'inactive_duration': inactive_duration,
                        'blank_timeout': timeout_seconds,
                        'will_blank': inactive_duration >= timeout_seconds,
                    },
                )
                if inactive_duration >= timeout_seconds:
                    logger.info(
                        'Screen blanking due to inactivity',
                        extra={'inactive_duration': inactive_duration},
                    )
                    store.dispatch(DisplayBlankAction())

            await asyncio.sleep(10)
            logger.verbose('=== INACTIVITY CHECK TICK ===')
    except Exception:
        logger.exception('Monitor inactivity task error')


def handle_blank_event(_: DisplayBlankEvent) -> None:
    """Handle screen blanking event."""
    logger.info('Blanking screen and turning off backlight')
    display.set_backlight(enabled=False)

def handle_unblank_event(_: DisplayUnblankEvent) -> None:
    """Handle screen unblanking event."""
    logger.info('Unblanking screen and turning on backlight')
    display.set_backlight(enabled=True)
    # Signal the inactivity monitor to wake up
    _unblank_event.set()


DISPLAY_TIMEOUT_MENU_ID = 'display:timeout'


@store.autorun(lambda state: state.display.selected_blank_timeout)
def timeout_options(selected_timeout: DisplayBlankTimeout) -> Sequence[Item]:
    """Generate menu items for timeout selection."""
    return [
        UboDispatchItem(
            key=timeout.value,
            label=timeout.get_label(),
            store_action=DisplaySetBlankTimeoutAction(timeout=timeout),
            **(
                SELECTED_ITEM_PARAMETERS
                if selected_timeout == timeout
                else UNSELECTED_ITEM_PARAMETERS
            ),
        )
        for timeout in DisplayBlankTimeout
    ]


def _register_display_action_handlers() -> None:
    """Register action handlers for display timeout settings."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
    )

    # Only register once
    if 'display:set_timeout:off' in get_registered_actions():
        return

    for timeout in DisplayBlankTimeout:
        def _make_timeout_handler(t: DisplayBlankTimeout) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(DisplaySetBlankTimeoutAction(timeout=t))

            return _handler

        register_action(
            f'display:set_timeout:{timeout.value}',
            _make_timeout_handler(timeout),
        )


@store.autorun(lambda state: state.display.selected_blank_timeout)
def update_display_dynamic_menu(selected_timeout: DisplayBlankTimeout) -> None:
    """Update the dynamic menu for display timeout settings (dumb UI)."""
    _register_display_action_handlers()

    # Convert timeout options to MenuItemData
    menu_items = tuple(
        MenuItemData(
            key=timeout.value,
            label=timeout.get_label(),
            icon=SELECTED_ITEM_PARAMETERS['icon']
            if selected_timeout == timeout
            else UNSELECTED_ITEM_PARAMETERS['icon'],
            action_id=f'display:set_timeout:{timeout.value}',
        )
        for timeout in DisplayBlankTimeout
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=DISPLAY_TIMEOUT_MENU_ID,
            title='Display Settings',
            heading='Screen Timeout',
            sub_heading='Select screen blank timeout',
            items=menu_items,
            placeholder='',
        ),
    )


def init_service() -> Subscriptions:
    """Initialize the display service."""
    from ubo_app.utils.async_ import create_task

    # Register path matcher for display settings navigation
    def _display_path_matcher(path: tuple[str, ...]) -> str | None:
        # Match: ('main', 'settings', <category>, '000-display:')
        if (
            len(path) == 4  # noqa: PLR2004
            and path[3] == 'display:'
        ):
            return DISPLAY_TIMEOUT_MENU_ID
        return None

    unregister_settings = register_path_menu_matcher(
        'display:settings',
        _display_path_matcher,
    )

    # Register persistent store
    register_persistent_store(
        'display:selected_blank_timeout',
        lambda state: state.display.selected_blank_timeout,
    )

    # Register settings menu
    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.HARDWARE,
            priority=10,
            label='Display',
            icon='󰍹',
        ),
    )

    # Initialize activity tracking
    store.dispatch(DisplayUpdateActivityAction())
    logger.info('Display service initialized with activity tracking')

    store.subscribe_event(DisplayBlankEvent, handle_blank_event)
    store.subscribe_event(DisplayUnblankEvent, handle_unblank_event)

    # Don't start monitor task during tests to prevent screen blanking
    # during screenshots
    if not IS_TEST_ENV:
        create_task(monitor_inactivity())
        logger.info('Screen blanking monitor task started')
    else:
        logger.info('Screen blanking disabled during tests')

    return [unregister_settings]


"""Sets up the display for the Raspberry Pi and manages its state."""

from __future__ import annotations

import asyncio
import time

from ubo_app.display import display
from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.display import (
    DisplayBlankAction,
    DisplayBlankEvent,
    DisplayState,
    DisplayUnblankAction,
    DisplayUnblankEvent,
    DisplayUpdateActivityAction,
)
from ubo_app.store.services.keypad import KeypadKeyPressAction

splash_screen = None


@store.with_state(
    lambda state: (
        state.display.is_blanked if hasattr(state, 'display') else False,
        state.keypad.is_consumed if hasattr(state, 'keypad') else False,
    ),
)
def handle_keypad_wake(is_blanked: bool, is_consumed: bool) -> None:  # noqa: FBT001
    """Wake up screen on any keypad press when blanked."""
    if is_blanked and not is_consumed:

        def on_keypress(_: KeypadKeyPressAction) -> None:
            logger.info('Waking up screen from keypad press - consuming key')
            store.dispatch(DisplayUnblankAction())

        return store.subscribe_action(KeypadKeyPressAction, on_keypress)
    return None


async def monitor_inactivity() -> None:
    """Monitor user inactivity and blank screen after timeout."""
    logger.info('=== MONITOR INACTIVITY TASK STARTED ===')

    try:
        while True:
            await asyncio.sleep(10)
            logger.info('=== INACTIVITY CHECK TICK ===')

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
                continue

            logger.info(
                'Inactivity check',
                extra={
                    'last_activity': display_state.last_activity_time,
                    'blank_timeout': display_state.blank_timeout,
                    'is_blanked': display_state.is_blanked,
                    'current_time': time.time(),
                },
            )

            if display_state.last_activity_time is not None:
                inactive_duration = time.time() - display_state.last_activity_time
                logger.info(
                    'Checking inactivity duration',
                    extra={
                        'inactive_duration': inactive_duration,
                        'blank_timeout': display_state.blank_timeout,
                        'will_blank': (
                            inactive_duration >= display_state.blank_timeout
                            and not display_state.is_blanked
                        ),
                    },
                )
                if (
                    inactive_duration >= display_state.blank_timeout
                    and not display_state.is_blanked
                ):
                    logger.info(
                        'Screen blanking due to inactivity',
                        extra={'inactive_duration': inactive_duration},
                    )
                    store.dispatch(DisplayBlankAction())
    except Exception:
        logger.exception('Monitor inactivity task error')


def handle_blank_event(_: DisplayBlankEvent) -> None:
    """Handle screen blanking event."""
    logger.info('=== HANDLE_BLANK_EVENT CALLED ===')
    logger.info('Blanking screen and turning off backlight')
    display.set_backlight(enabled=False)
    logger.info('=== BLANK EVENT HANDLING COMPLETE ===')


def handle_unblank_event(_: DisplayUnblankEvent) -> None:
    """Handle screen unblanking event."""
    logger.info('Unblanking screen and turning on backlight')
    display.set_backlight(enabled=True)


def init_service() -> None:
    """Initialize the display service."""
    from ubo_app.utils.async_ import create_task

    # Initialize activity tracking
    store.dispatch(DisplayUpdateActivityAction())
    logger.info('Display service initialized with activity tracking')

    store.subscribe_event(DisplayBlankEvent, handle_blank_event)
    store.subscribe_event(DisplayUnblankEvent, handle_unblank_event)

    create_task(monitor_inactivity())

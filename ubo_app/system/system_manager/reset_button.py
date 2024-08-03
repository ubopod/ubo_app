"""Reset button module."""

import subprocess
import time

from ubo_app.logging import get_logger

logger = get_logger('system-manager')

RESET_BUTTON_PIN = 27
LONG_PRESS_TIME = 3
SHORT_PRESS_TIME = 0.5


def setup_reset_button() -> None:
    """Set the reset button."""
    from gpiozero import Button

    reset_button = Button(RESET_BUTTON_PIN)
    state = {}

    def reset_button_pressed(_: int) -> None:
        state['press_time'] = time.time()

    def reset_button_released(_: int) -> None:
        release_time = time.time()
        if 'press_time' in state:
            duration = release_time - state['press_time']
            if duration > LONG_PRESS_TIME:
                logger.info('Reset button pressed for 3 seconds')

                # Restart the pod
                subprocess.run(  # noqa: S603
                    ['/usr/bin/env', 'systemctl', 'reboot', '-i'],
                    check=True,
                )
            elif duration > SHORT_PRESS_TIME:
                logger.info('Reset button pressed for less than 3 seconds')

                # Kill the UBO process
                subprocess.run(  # noqa: S603
                    ['/usr/bin/env', 'killall', '-9', 'ubo'],
                    check=True,
                )

    reset_button.when_pressed = reset_button_pressed
    reset_button.when_released = reset_button_released

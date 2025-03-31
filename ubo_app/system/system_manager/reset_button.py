"""Reset button module."""

import pwd
import subprocess
import time

from ubo_app.constants import USERNAME
from ubo_app.logger import get_logger
from ubo_app.system.system_manager.led import LEDManager

logger = get_logger('system-manager')

RESET_BUTTON_PIN = 27
LONG_PRESS_TIME = 5
SHORT_PRESS_TIME = 1
RAPID_PRESS_TIME = 1
RAPID_PRESS_COUNT = 3


def setup_reset_button(led_manager: LEDManager) -> None:
    """Set the reset button."""
    from gpiozero import Button

    reset_button = Button(RESET_BUTTON_PIN)
    state = {}
    state['latest_releases'] = []

    def reset_button_pressed(_: int) -> None:
        state['press_time'] = time.time()

    def reset_button_released(_: int) -> None:
        release_time = time.time()
        state['latest_releases'] = [
            release_time,
        ] + [t for t in state['latest_releases'] if release_time - t < RAPID_PRESS_TIME]
        if 'press_time' in state:
            duration = release_time - state['press_time']
            logger.info(
                'Reset button released',
                extra={
                    'duration': duration,
                    'press_time': state['press_time'],
                    'release_time': release_time,
                    'latest_releases': state['latest_releases'],
                    'SHORT_PRESS_TIME': SHORT_PRESS_TIME,
                    'LONG_PRESS_TIME': LONG_PRESS_TIME,
                    'RAPID_PRESS_TIME': RAPID_PRESS_TIME,
                    'RAPID_PRESS_COUNT': RAPID_PRESS_COUNT,
                },
            )

            if duration > LONG_PRESS_TIME:
                # Restart the pod
                led_manager.run_command_thread_safe(
                    ['blink', '255', '0', '0', '200', '2'],
                )
                subprocess.run(  # noqa: S603
                    ['/usr/bin/env', 'systemctl', 'reboot', '-i'],
                    check=False,
                )
            elif duration > SHORT_PRESS_TIME:
                # Restart the ubo service
                led_manager.run_command_thread_safe(
                    ['blink', '255', '255', '0', '200', '1'],
                )
                uid = pwd.getpwnam(USERNAME).pw_uid
                subprocess.run(  # noqa: S603
                    [
                        '/usr/bin/env',
                        'sudo',
                        f'XDG_RUNTIME_DIR=/run/user/{uid}',
                        '-u',
                        USERNAME,
                        'systemctl',
                        '--user',
                        'restart',
                        'ubo-app',
                    ],
                    check=False,
                )
                time.sleep(1)
                led_manager.run_initialization_loop()
            elif len(state['latest_releases']) == RAPID_PRESS_COUNT:
                # Kill the UBO process
                led_manager.run_command_thread_safe(
                    ['blink', '255', '0', '0', '200', '1'],
                )
                subprocess.run(  # noqa: S603
                    ['/usr/bin/env', 'killall', '-9', 'ubo'],
                    check=False,
                )
                time.sleep(1)
                led_manager.run_initialization_loop()

    reset_button.when_pressed = reset_button_pressed
    reset_button.when_released = reset_button_released

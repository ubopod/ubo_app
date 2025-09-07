"""Infrared receiver for system manager."""

import asyncio
import functools
import queue
import re
from collections.abc import Iterator
from pathlib import Path
from threading import Thread

from ubo_app.logger import get_logger

logger = get_logger('system-manager')


class InfraredManager:
    """Manager for infrared functionality."""

    def __init__(self) -> None:
        """Initialize the infrared manager."""
        self.loop = asyncio.new_event_loop()
        self.event_loop_thread: Thread | None = None
        self.ir_code_queue = queue.Queue(1)
        self.stop_event = asyncio.Event()

    def handle_command(self, command: str) -> Iterator[str] | str | None:
        """Handle infrared commands."""
        logger.info('Infrared command received', extra={'command': command})
        if command == 'start':
            if not self.event_loop_thread:
                self.stop_event.clear()
                self.event_loop_thread = Thread(
                    target=functools.partial(
                        self.loop.run_until_complete,
                        self._monitor_ir(),
                    ),
                    daemon=True,
                )
                self.event_loop_thread.start()
                logger.info('Starting IR monitoring process')
            else:
                logger.info('IR monitoring process already running')
            return 'started'
        if command == 'stop':
            if self.event_loop_thread:
                self.stop_event.set()
                logger.info('Stopping IR monitoring process')
                self.event_loop_thread.join()
                self.event_loop_thread = None

            return 'stopped'
        if command == 'receive':
            logger.info('Processing receive command')
            while True:
                try:
                    code = self.ir_code_queue.get()
                except Exception:
                    logger.exception('Error retrieving IR code from queue')
                    return 'nocode'
                else:
                    logger.debug('Retrieved IR code from queue', extra={'code': code})
                    yield code
        else:
            return None

    async def _monitor_ir(self) -> None:
        """Monitor infrared signals and put received IR codes in the queue."""
        # First, find the correct IR receiver device index by checking symlinks
        logger.info('Finding IR receiver device index')

        device_index = self._get_ir_receiver_index()
        if not device_index:
            logger.error('Failed to find IR receiver device index')
            return

        logger.info('Starting ir-keytable process')
        process = await asyncio.create_subprocess_exec(
            'stdbuf',
            '-i0',
            '-o0',
            '-e0',
            'ir-keytable',
            '-c',
            '-p',
            'all',
            '-t',
            '-s',
            device_index,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        if not process.stdout:
            logger.error('Failed to start ir-keytable process - no stdout pipe')
            return

        logger.info('Started ir-keytable process with PID %d', process.pid)

        while True:
            result = await next(
                asyncio.as_completed(
                    (
                        self.stop_event.wait(),
                        process.stdout.readline(),
                    ),
                ),
            )
            if result is True:
                logger.info('Stopping IR monitoring process')
                process.kill()
                break

            line = result.decode().strip()
            logger.debug('Raw IR output', extra={'line': line})

            # Parse lirc protocol lines except repeat codes
            if not line or 'lirc protocol' not in line or 'repeat' in line:
                await asyncio.sleep(0.1)
                continue

            match = re.search(
                r'lirc protocol\((\w+)\).*scancode = (0x[0-9a-fA-F]+)',
                line,
            )
            if not match:
                logger.warning('Failed to parse IR code', extra={'line': line})
                continue

            protocol, scancode = match.group(1), match.group(2)

            logger.info(
                'IR code received',
                extra={'protocol': protocol, 'scancode': scancode},
            )
            code_str = f'{protocol}:{scancode}'
            # Put the code in the queue
            self.ir_code_queue.put(code_str)

    def _get_ir_receiver_index(self) -> str | None:
        """Get the IR receiver device index by checking symlinks."""
        try:
            # Scan /sys/class/rc/ directory for ir-receiver symlinks
            rc_dir = '/sys/class/rc'
            if Path(rc_dir).exists():
                for rc_device in Path(rc_dir).iterdir():
                    if rc_device.is_symlink():
                        link_target = Path.readlink(rc_device)
                        logger.debug(
                            'Found RC device',
                            extra={'device': rc_device, 'link_target': link_target},
                        )
                        if 'ir-receiver' in str(link_target):
                            device_name = rc_device.name
                            logger.info(
                                'Found IR receiver device index',
                                extra={
                                    'device_index': device_name,
                                    'link_target': link_target,
                                },
                            )
                            return device_name
        except OSError:
            logger.exception('Error scanning /sys/class/rc/')

        logger.error('Failed to find IR receiver device index')
        return None


infrared_manager = InfraredManager()
infrared_handler = infrared_manager.handle_command

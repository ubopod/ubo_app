"""Infrared receiver for system manager."""

import asyncio
import queue
import re
import time
from threading import Thread

from ubo_app.logger import get_logger

logger = get_logger('system-manager')


class InfraredManager:
    """Manager for infrared functionality."""

    def __init__(self) -> None:
        """Initialize the infrared manager."""
        self.process: asyncio.subprocess.Process | None = None
        self.loop = asyncio.new_event_loop()
        Thread(target=self.loop.run_forever, daemon=True).start()
        self.ir_code_queue = queue.Queue()  # Simple thread-safe queue for IR codes
        self.ir_monitor_running = False
        self.monitor_task = None
        self.stdout_task = None
        self.stderr_task = None

    def handle_command(self, command: str) -> str | None:
        """Handle infrared commands."""
        logger.info('Infrared command received: %s', command)
        if command == 'start':
            if not self.ir_monitor_running:
                logger.info('Starting IR monitoring process')
                self.monitor_task = asyncio.run_coroutine_threadsafe(
                    self._monitor_ir(),
                    self.loop,
                )
                self.ir_monitor_running = True
            else:
                logger.info('IR monitoring process already running')
            return 'started'
        if command == 'stop':
            if self.monitor_task is not None:
                logger.info('Stopping IR monitoring process')
                self.monitor_task.cancel()
                self.ir_monitor_running = False
                # Also terminate the process if it's running
                if self.process and self.process.returncode is None:
                    self.process.terminate()
            return 'stopped'
        if command == 'receive':
            logger.info('Processing receive command')
            try:
                # Start the IR monitoring process if it's not already running
                if not self.ir_monitor_running:
                    logger.info('Starting IR monitoring process')
                    self.monitor_task = asyncio.run_coroutine_threadsafe(
                        self._monitor_ir(),
                        self.loop,
                    )
                    self.ir_monitor_running = True

                while self.ir_code_queue.empty():
                    time.sleep(0.1)
                code = self.ir_code_queue.get()
                logger.info('Retrieved IR code from queue: %s', code)
                return code  # noqa: TRY300
            except Exception as e:
                logger.exception('Error retrieving IR code from queue', exc_info=e)
                return 'nocode'
        return None

    async def _monitor_ir(self) -> None:
        """Monitor infrared signals and put received IR codes in the queue."""
        logger.info('Starting ir-keytable process')
        self.process = await asyncio.create_subprocess_exec(
            'sudo',
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
            'rc1',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if not self.process.stdout or not self.process.stderr:
            logger.error('Failed to start ir-keytable process - no stdout/stderr pipes')
            self.process = None
            return

        logger.info('Started ir-keytable process with PID %d', self.process.pid)

        try:
            while True:
                # Check if process is still running
                if self.process.returncode is not None:
                    logger.info('ir-keytable process exited with code %d',
                              self.process.returncode)
                    break
                line = await self.process.stdout.readline()
                if line:
                    line_str = line.decode().strip()
                    logger.info('Raw IR output: %s', line_str)

                    # Parse lirc protocol lines
                    if 'lirc protocol' in line_str:
                        self._parse_and_queue_ir_code(line_str)
                else:
                    logger.debug('No more stdout output')
                    break

        except Exception as e:
            logger.exception('Error in IR monitoring', exc_info=e)
        finally:
            if self.process and self.process.returncode is None:
                logger.info('Terminating ir-keytable process')
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=1)
                except TimeoutError:
                    logger.warning('Process did not terminate, killing it')
                    self.process.kill()
            self.process = None


    def _parse_and_queue_ir_code(self, line_str: str) -> None:
        """Parse an IR code from a line and add it to the queue if valid.

        Args:
            line_str: The line to parse for IR codes

        """
        protocol_match = re.search(r'lirc protocol\((\w+)\)', line_str)
        scancode_match = re.search(r'scancode = (0x[0-9a-fA-F]+)', line_str)
        is_repeat = 'repeat' in line_str

        if not (protocol_match and scancode_match):
            logger.warning('Failed to parse IR code: %s', line_str)
            return

        protocol = protocol_match.group(1)
        scancode = scancode_match.group(1)

        logger.info(
            'IR code received: protocol=%s, scancode=%s, repeat=%s',
            protocol,
            scancode,
            is_repeat,
        )

        # Only process non-repeat codes
        if not is_repeat:
            logger.info('IR code received: %s:%s', protocol, scancode)
            # Put the code in the queue
            code_str = f'{protocol}:{scancode}'
            self.ir_code_queue.put(code_str)


infrared_manager = InfraredManager()
infrared_handler = infrared_manager.handle_command

"""Tests for assistant subprocess Loguru file logging."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from loguru import logger

from ubo_assistant.logging import setup_file_logging


class AssistantLoggingTest(unittest.TestCase):
    """Assistant Loguru file sink behavior."""

    def test_setup_file_logging_writes_info_by_default(self) -> None:
        """INFO logs are written to the configured assistant log file."""
        with TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / 'ubo-assistant.log'
            environment = {'UBO_ASSISTANT_LOG_PATH': str(log_path)}
            with patch.dict(os.environ, environment, clear=False):
                os.environ.pop('UBO_ASSISTANT_LOG_LEVEL', None)
                sink_id = setup_file_logging()
            try:
                logger.info('assistant file logging smoke test')
                logger.complete()
            finally:
                logger.remove(sink_id)

            self.assertTrue(log_path.exists())  # noqa: PT009
            self.assertIn(  # noqa: PT009
                'assistant file logging smoke test',
                log_path.read_text(),
            )

    def test_invalid_log_level_falls_back_to_info(self) -> None:
        """Invalid assistant log levels do not prevent INFO file logging."""
        with TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / 'ubo-assistant.log'
            environment = {
                'UBO_ASSISTANT_LOG_PATH': str(log_path),
                'UBO_ASSISTANT_LOG_LEVEL': 'verbose-ish',
            }
            with patch.dict(os.environ, environment, clear=False):
                sink_id = setup_file_logging()
            try:
                logger.info('assistant invalid level fallback test')
                logger.complete()
            finally:
                logger.remove(sink_id)

            self.assertIn(  # noqa: PT009
                'assistant invalid level fallback test',
                log_path.read_text(),
            )


if __name__ == '__main__':
    unittest.main()

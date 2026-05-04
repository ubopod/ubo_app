"""Tests for optional Pipecat debugging integrations."""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar, cast
from unittest.mock import patch

from ubo_assistant.pipecat_debug import (
    SupportsWhiskerObserver,
    attach_whisker_observer,
    is_whisker_enabled,
)


class FakeWhiskerObserver:
    """Fake Whisker observer that records initialization parameters."""

    calls: ClassVar[list[tuple[object, dict[str, str]]]] = []

    def __init__(self, pipeline: object, **kwargs: str) -> None:
        """Record observer construction."""
        self.pipeline = pipeline
        self.kwargs = kwargs
        self.calls.append((pipeline, kwargs))


class FakeWhiskerModule(types.ModuleType):
    """Fake pipecat_whisker module."""

    WhiskerObserver = FakeWhiskerObserver


class FakeTask:
    """Minimal PipelineTask surface used by Whisker attachment."""

    def __init__(self) -> None:
        """Initialize fake task state."""
        self.pipeline = object()
        self.observers: list[object] = []

    def add_observer(self, observer: object) -> None:
        """Record attached observers."""
        self.observers.append(observer)


class PipecatDebugTests(unittest.TestCase):
    """Environment-gated Whisker integration behavior."""

    def setUp(self) -> None:
        """Reset fake observer state before each test."""
        FakeWhiskerObserver.calls = []

    def test_whisker_is_disabled_by_default(self) -> None:
        """Whisker is opt-in and does not require the dependency when disabled."""
        task = FakeTask()
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith('UBO_ASSISTANT_WHISKER_')
        }

        with patch.dict(os.environ, environment, clear=True):
            sys.modules.pop('pipecat_whisker', None)

            self.assertFalse(is_whisker_enabled())  # noqa: PT009
            self.assertFalse(  # noqa: PT009
                attach_whisker_observer(cast('SupportsWhiskerObserver', task)),
            )

        self.assertEqual(task.observers, [])  # noqa: PT009

    def test_truthy_env_values_enable_whisker(self) -> None:
        """Common truthy env values enable Whisker."""
        for value in ('1', 'true', 'TRUE', 'yes', 'on'):
            with self.subTest(value=value):
                self.assertTrue(  # noqa: PT009
                    is_whisker_enabled({'UBO_ASSISTANT_WHISKER_ENABLED': value}),
                )

    def test_invalid_env_values_disable_whisker(self) -> None:
        """Falsey and unknown env values leave Whisker disabled."""
        for value in ('', '0', 'false', 'no', 'debug'):
            with self.subTest(value=value):
                self.assertFalse(  # noqa: PT009
                    is_whisker_enabled({'UBO_ASSISTANT_WHISKER_ENABLED': value}),
                )

    def test_attach_whisker_observer_when_enabled(self) -> None:
        """Enabled Whisker adds an observer to the Pipecat task."""
        fake_module = FakeWhiskerModule('pipecat_whisker')
        task = FakeTask()

        with (
            patch.dict(sys.modules, {'pipecat_whisker': fake_module}),
            patch.dict(os.environ, {'UBO_ASSISTANT_WHISKER_ENABLED': 'true'}),
        ):
            self.assertTrue(  # noqa: PT009
                attach_whisker_observer(cast('SupportsWhiskerObserver', task)),
            )

        self.assertEqual(len(task.observers), 1)  # noqa: PT009
        self.assertEqual(FakeWhiskerObserver.calls, [(task.pipeline, {})])  # noqa: PT009

    def test_attach_whisker_observer_passes_file_name(self) -> None:
        """The optional session file path is passed to Whisker."""
        fake_module = FakeWhiskerModule('pipecat_whisker')
        task = FakeTask()
        with TemporaryDirectory() as temporary_directory:
            whisker_file = str(Path(temporary_directory) / 'whisker.bin')

            with (
                patch.dict(sys.modules, {'pipecat_whisker': fake_module}),
                patch.dict(
                    os.environ,
                    {
                        'UBO_ASSISTANT_WHISKER_ENABLED': 'true',
                        'UBO_ASSISTANT_WHISKER_FILE': whisker_file,
                    },
                ),
            ):
                self.assertTrue(  # noqa: PT009
                    attach_whisker_observer(cast('SupportsWhiskerObserver', task)),
                )

            self.assertEqual(  # noqa: PT009
                FakeWhiskerObserver.calls,
                [(task.pipeline, {'file_name': whisker_file})],
            )


if __name__ == '__main__':
    unittest.main()

"""Regression tests for Piper TTS first-time setup.

Bug: on first-time setup the default Piper voice isn't on disk yet (it's
downloaded on demand). Previously ``PiperTTSService.__init__`` eagerly loaded
the model and raised, so ``UboTTSService.piper_tts`` became ``None``. Pipecat
1.0 freezes the switcher's service list at construction, so a ``None`` Piper
slot is dropped from ``service_map`` forever — selecting Piper fell through to
the no-op and stayed silent until the app was restarted (after which the file
existed and the load succeeded).

These tests pin the fix: the service constructs without the model on disk,
stays a selectable switch target, and loads the voice lazily once downloaded.
``DATA_PATH`` is pointed at an empty temp dir so first-time setup is simulated
deterministically with no network and no real model.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast
from unittest.mock import MagicMock, patch

import ubo_assistant.piper as piper_module
from ubo_assistant.piper import DEFAULT_PIPER_VOICE_ID, PiperTTSService, _voice_path
from ubo_assistant.ubo_tts import TTSServiceConfig, UboTTSService

if TYPE_CHECKING:
    from ubo_bindings.client import UboRPCClient

F = TypeVar('F', bound=Callable[..., object])


class FakeClient:
    """Minimal client surface used by the switcher under test."""

    def dispatch(self, *, action: object) -> None:
        """Ignore dispatched assistance reports."""
        _ = action

    def autorun(self, selectors: list[str]) -> Callable[[F], F]:
        """Return a decorator without invoking it (no autoruns in tests)."""
        _ = selectors

        def decorator(function: F) -> F:
            return function

        return decorator


class PiperFirstTimeSetupTests(unittest.IsolatedAsyncioTestCase):
    """Piper must survive (and stay selectable) before its model is downloaded."""

    async def test_constructs_without_model_file(self) -> None:
        """PiperTTSService must not raise when the voice file is absent."""
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            piper_module,
            'DATA_PATH',
            Path(tmp),
        ):
            service = PiperTTSService(voice_id=DEFAULT_PIPER_VOICE_ID)

            self.assertIsNone(service._client)  # noqa: PT009, SLF001
            self.assertIsNone(service._loaded_voice_id)  # noqa: PT009, SLF001
            self.assertEqual(  # noqa: PT009
                service._requested_voice_id,  # noqa: SLF001
                DEFAULT_PIPER_VOICE_ID,
            )

    async def test_piper_stays_selectable_in_switcher_without_model(self) -> None:
        """Selecting Piper before download must switch to Piper, not the no-op."""
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            piper_module,
            'DATA_PATH',
            Path(tmp),
        ):
            switcher = UboTTSService(
                client=cast('UboRPCClient', FakeClient()),
                config=TTSServiceConfig(),
                google_credentials=None,
                selector='state.assistant.selected_tts',
            )

            # The Piper slot is a real service, not dropped from the map.
            self.assertIsNotNone(switcher.piper_tts)  # noqa: PT009
            self.assertIn('piper', switcher.service_map)  # noqa: PT009

            await switcher.set_selected_service('piper')

            self.assertIs(  # noqa: PT009
                switcher.selected_service,
                switcher.piper_tts,
            )
            self.assertEqual(  # noqa: PT009
                switcher._current_service_id,  # noqa: SLF001
                'piper',
            )
            self.assertIsNot(  # noqa: PT009
                switcher.strategy.active_service,
                switcher._noop_service,  # noqa: SLF001
            )

    async def test_voice_loads_lazily_once_downloaded(self) -> None:
        """A voice downloaded after construction loads on the next utterance."""
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            piper_module,
            'DATA_PATH',
            Path(tmp),
        ):
            service = PiperTTSService(voice_id=DEFAULT_PIPER_VOICE_ID)
            self.assertIsNone(service._client)  # noqa: PT009, SLF001

            # Simulate the core process finishing the download.
            model_path = _voice_path(DEFAULT_PIPER_VOICE_ID)
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.touch()

            fake_voice = MagicMock()
            fake_voice.config.sample_rate = 22050

            service.request_voice(DEFAULT_PIPER_VOICE_ID)
            with patch('piper.voice.PiperVoice.load', return_value=fake_voice):
                await service._ensure_voice_loaded()  # noqa: SLF001

            self.assertIs(service._client, fake_voice)  # noqa: PT009, SLF001
            self.assertEqual(  # noqa: PT009
                service._loaded_voice_id,  # noqa: SLF001
                DEFAULT_PIPER_VOICE_ID,
            )


if __name__ == '__main__':
    unittest.main()

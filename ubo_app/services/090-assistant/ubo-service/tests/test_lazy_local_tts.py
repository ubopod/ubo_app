"""Regression tests pinning lazy model loading for the local TTS engines.

Bug: both local engines loaded their ONNX weights during ``__init__``, gated
only on *"is the model file on disk"* — never on whether the user had actually
selected that provider. On a device with both downloaded, that cost ~515 MB of
resident memory at every boot while the selected provider was a cloud service:
``Kokoro()`` alone measured +421 MB, ``PiperVoice.load()`` +94 MB.

These tests pin the fix. Construction must stay cheap and must not touch the
weights; the model is materialized only when the engine is selected (Kokoro) or
about to speak (Piper). Both engines must still hold their slot in the
switcher's frozen service list, because Pipecat drops a ``None`` slot forever.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, TypeVar, cast
from unittest.mock import AsyncMock, MagicMock, patch

import ubo_assistant.piper as piper_module
import ubo_assistant.ubo_tts as ubo_tts_module
from ubo_assistant.piper import DEFAULT_PIPER_VOICE_ID, PiperTTSService, _voice_path
from ubo_assistant.ubo_tts import GenericTTSProxy, TTSServiceConfig, UboTTSService

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


class PiperLazyLoadTests(unittest.IsolatedAsyncioTestCase):
    """Piper must not read its voice model until it is about to speak."""

    async def test_does_not_load_model_when_file_is_present(self) -> None:
        """The decisive case: model on disk, but nothing selected Piper yet."""
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                piper_module,
                'DATA_PATH',
                Path(tmp),
            ),
        ):
            model_path = _voice_path(DEFAULT_PIPER_VOICE_ID)
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.touch()

            with patch('piper.voice.PiperVoice.load') as load:
                service = PiperTTSService(voice_id=DEFAULT_PIPER_VOICE_ID)

                load.assert_not_called()

            self.assertIsNone(service._client)  # noqa: PT009, SLF001
            self.assertIsNone(service._loaded_voice_id)  # noqa: PT009, SLF001

    async def test_loads_model_on_first_utterance(self) -> None:
        """The deferred load still happens, driven by ``_ensure_voice_loaded``."""
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                piper_module,
                'DATA_PATH',
                Path(tmp),
            ),
        ):
            model_path = _voice_path(DEFAULT_PIPER_VOICE_ID)
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.touch()

            service = PiperTTSService(voice_id=DEFAULT_PIPER_VOICE_ID)

            fake_voice = MagicMock()
            fake_voice.config.sample_rate = 22050
            with patch('piper.voice.PiperVoice.load', return_value=fake_voice):
                await service._ensure_voice_loaded()  # noqa: SLF001

            self.assertIs(service._client, fake_voice)  # noqa: PT009, SLF001
            self.assertEqual(  # noqa: PT009
                service._loaded_voice_id,  # noqa: SLF001
                DEFAULT_PIPER_VOICE_ID,
            )


class KokoroLazyLoadTests(unittest.IsolatedAsyncioTestCase):
    """Kokoro must not build its 325 MB session until it is selected."""

    def _switcher(self) -> UboTTSService:
        return UboTTSService(
            client=cast('UboRPCClient', FakeClient()),
            config=TTSServiceConfig(),
            google_credentials=None,
            selector='state.assistant.selected_tts',
        )

    async def test_not_constructed_at_startup_when_files_present(self) -> None:
        """Both model files on disk must not be enough to build the service."""
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / 'kokoro-v1.0.onnx'
            voices = Path(tmp) / 'voices-v1.0.bin'
            model.touch()
            voices.touch()

            with (
                patch.object(
                    ubo_tts_module,
                    'KOKORO_MODEL_PATH',
                    model,
                ),
                patch.object(
                    ubo_tts_module,
                    'KOKORO_VOICES_PATH',
                    voices,
                ),
                patch.object(
                    ubo_tts_module,
                    'KokoroTTSService',
                ) as kokoro_class,
            ):
                switcher = self._switcher()

                kokoro_class.assert_not_called()

            self.assertIn('kokoro', switcher.service_map)  # noqa: PT009
            self.assertIsInstance(switcher.kokoro_tts, GenericTTSProxy)  # noqa: PT009
            self.assertIsNone(  # noqa: PT009
                cast('GenericTTSProxy', switcher.kokoro_tts).service,
            )

    async def test_constructed_when_selected(self) -> None:
        """Selecting Kokoro builds the real service behind the proxy."""
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / 'kokoro-v1.0.onnx'
            voices = Path(tmp) / 'voices-v1.0.bin'
            model.touch()
            voices.touch()

            with (
                patch.object(
                    ubo_tts_module,
                    'KOKORO_MODEL_PATH',
                    model,
                ),
                patch.object(
                    ubo_tts_module,
                    'KOKORO_VOICES_PATH',
                    voices,
                ),
                patch.object(
                    ubo_tts_module,
                    'KokoroTTSService',
                ) as kokoro_class,
            ):
                switcher = self._switcher()
                await switcher.set_selected_service('kokoro')

                kokoro_class.assert_called_once()

                proxy = cast('GenericTTSProxy', switcher.kokoro_tts)
                self.assertIs(proxy.service, kokoro_class.return_value)  # noqa: PT009

                # Selecting again must not rebuild the session.
                await switcher.set_selected_service('kokoro')
                kokoro_class.assert_called_once()

    async def test_stays_selectable_when_not_downloaded(self) -> None:
        """Without the files, Kokoro keeps its slot and simply stays silent."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'absent.onnx'

            with (
                patch.object(
                    ubo_tts_module,
                    'KOKORO_MODEL_PATH',
                    missing,
                ),
                patch.object(
                    ubo_tts_module,
                    'KOKORO_VOICES_PATH',
                    missing,
                ),
                patch.object(
                    ubo_tts_module,
                    'KokoroTTSService',
                ) as kokoro_class,
            ):
                switcher = self._switcher()
                await switcher.set_selected_service('kokoro')

                kokoro_class.assert_not_called()

            self.assertIn('kokoro', switcher.service_map)  # noqa: PT009
            self.assertIs(  # noqa: PT009
                switcher.selected_service,
                switcher.kokoro_tts,
            )


class FakeKokoroService:
    """Stand-in for ``KokoroTTSService`` that records its own teardown.

    A real class rather than a ``MagicMock`` because the production code uses
    ``isinstance`` to decide whether to call ``release()``, and a mock is not
    a type.
    """

    instances: ClassVar[list[FakeKokoroService]] = []

    def __init__(self, *, voice_id: str) -> None:
        """Record the requested voice and register the instance."""
        self.voice_id = voice_id
        self.released = False
        self.cleanup = AsyncMock()
        self.queue_frame = AsyncMock()
        self.setup = AsyncMock()
        FakeKokoroService.instances.append(self)

    def release(self) -> None:
        """Record that the weights were dropped."""
        self.released = True


class LocalEngineReleaseTests(unittest.IsolatedAsyncioTestCase):
    """Deselecting a local engine must give the weights back.

    Loading lazily is only half the job: before this, trying Kokoro or Piper
    once pinned their memory for the life of the subprocess, so an assistant
    that had briefly spoken locally sat at ~990 MB instead of ~346 MB even
    after the user switched back to a cloud provider.

    ``piper`` is used as the "other" selection throughout rather than a cloud
    provider, because the cloud branch of ``set_selected_service`` reaches for
    real secrets.
    """

    def _switcher(self) -> UboTTSService:
        return UboTTSService(
            client=cast('UboRPCClient', FakeClient()),
            config=TTSServiceConfig(),
            google_credentials=None,
            selector='state.assistant.selected_tts',
        )

    async def test_kokoro_released_when_deselected(self) -> None:
        """Switching away from Kokoro tears down the onnxruntime session."""
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / 'kokoro-v1.0.onnx'
            voices = Path(tmp) / 'voices-v1.0.bin'
            model.touch()
            voices.touch()

            FakeKokoroService.instances.clear()
            with (
                patch.object(ubo_tts_module, 'KOKORO_MODEL_PATH', model),
                patch.object(ubo_tts_module, 'KOKORO_VOICES_PATH', voices),
                patch.object(
                    ubo_tts_module,
                    'KokoroTTSService',
                    FakeKokoroService,
                ),
            ):
                switcher = self._switcher()
                await switcher.set_selected_service('kokoro')

                proxy = cast('GenericTTSProxy', switcher.kokoro_tts)
                service = FakeKokoroService.instances[0]
                self.assertIs(proxy.service, service)  # noqa: PT009

                await switcher.set_selected_service('piper')

                self.assertIsNone(proxy.service)  # noqa: PT009
                service.cleanup.assert_awaited()
                # Dropping the reference alone left the weights resident
                # on-device; the explicit teardown is what frees them.
                self.assertTrue(service.released)  # noqa: PT009

                # Coming back rebuilds it, so releasing isn't a one-way door.
                await switcher.set_selected_service('kokoro')
                self.assertEqual(len(FakeKokoroService.instances), 2)  # noqa: PT009
                self.assertIs(  # noqa: PT009
                    proxy.service,
                    FakeKokoroService.instances[1],
                )

    async def test_piper_voice_released_when_deselected(self) -> None:
        """Switching away from Piper drops the loaded voice model."""
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                piper_module,
                'DATA_PATH',
                Path(tmp),
            ),
        ):
            switcher = self._switcher()
            piper = cast('PiperTTSService', switcher.piper_tts)

            # Stand in for a voice loaded by the first utterance.
            piper._client = MagicMock()  # noqa: SLF001
            piper._loaded_voice_id = DEFAULT_PIPER_VOICE_ID  # noqa: SLF001

            await switcher.set_selected_service('kokoro')

            self.assertIsNone(piper._client)  # noqa: PT009, SLF001
            self.assertIsNone(piper._loaded_voice_id)  # noqa: PT009, SLF001

    async def test_selected_engine_is_not_released(self) -> None:
        """The engine the user just picked must survive its own selection."""
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                piper_module,
                'DATA_PATH',
                Path(tmp),
            ),
        ):
            switcher = self._switcher()
            piper = cast('PiperTTSService', switcher.piper_tts)

            client = MagicMock()
            piper._client = client  # noqa: SLF001
            piper._loaded_voice_id = DEFAULT_PIPER_VOICE_ID  # noqa: SLF001

            await switcher.set_selected_service('piper')

            self.assertIs(piper._client, client)  # noqa: PT009, SLF001


if __name__ == '__main__':
    unittest.main()

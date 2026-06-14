"""Tests for lazy model loading in :class:`VoskSTTService`.

Regression guard: constructing the service must never raise when the model
isn't on disk yet (e.g. it's still downloading/extracting when the assistant
subprocess starts). An eager load there used to throw and permanently kill the
Vosk slot, so selecting Vosk yielded "Selected service is not available" with
no recovery. The model now loads lazily and self-heals once it's present.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ubo_assistant.vosk import DEFAULT_VOSK_MODEL_ID, VoskSTTService


class VoskLazyLoadTests(unittest.IsolatedAsyncioTestCase):
    """Construction and on-demand model loading for VoskSTTService."""

    def setUp(self) -> None:
        """Point DATA_PATH at an empty temp dir with no model present."""
        self._tmp = tempfile.TemporaryDirectory()
        self.data_path = Path(self._tmp.name)
        patcher = patch('ubo_assistant.vosk.DATA_PATH', self.data_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_construction_without_model_does_not_raise(self) -> None:
        """Constructing with an absent model leaves the service unloaded."""
        service = VoskSTTService(model_id=DEFAULT_VOSK_MODEL_ID)

        self.assertIsNone(service._client)  # noqa: PT009, SLF001
        self.assertIsNone(service._loaded_model_id)  # noqa: PT009, SLF001
        self.assertEqual(  # noqa: PT009
            service._requested_model_id,  # noqa: SLF001
            DEFAULT_VOSK_MODEL_ID,
        )

    async def test_ensure_model_loaded_noop_when_absent(self) -> None:
        """A not-yet-downloaded model is skipped, keeping the client None."""
        service = VoskSTTService(model_id=DEFAULT_VOSK_MODEL_ID)

        await service._ensure_model_loaded()  # noqa: SLF001

        self.assertIsNone(service._client)  # noqa: PT009, SLF001
        self.assertIsNone(service._loaded_model_id)  # noqa: PT009, SLF001

    async def test_ensure_model_loaded_loads_when_present(self) -> None:
        """Once the model is on disk, the next reconcile loads it."""
        service = VoskSTTService(model_id=DEFAULT_VOSK_MODEL_ID)
        (self.data_path / DEFAULT_VOSK_MODEL_ID).mkdir()

        fake_recognizer = MagicMock(name='KaldiRecognizer')
        with (
            patch('ubo_assistant.vosk.Model', return_value=MagicMock(name='Model')),
            patch(
                'ubo_assistant.vosk.KaldiRecognizer',
                return_value=fake_recognizer,
            ),
        ):
            await service._ensure_model_loaded()  # noqa: SLF001

        self.assertIs(service._client, fake_recognizer)  # noqa: PT009, SLF001
        self.assertEqual(  # noqa: PT009
            service._loaded_model_id,  # noqa: SLF001
            DEFAULT_VOSK_MODEL_ID,
        )


if __name__ == '__main__':
    unittest.main()

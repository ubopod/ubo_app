"""Tests for ``UboOutputTransport`` interruption handling.

Verifies that on every ``InterruptionFrame`` the transport resets its
``_assistance_id`` (new uuid) and resets ``_audio_assistance_index`` /
``_video_assistance_index`` to zero — so the next utterance's audio chunks
arrive at ubo-core's ``audio_manager`` under a fresh sequence id starting at
index 0, instead of colliding with the just-cleared buffer state.
"""

from __future__ import annotations

import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pipecat.frames.frames import InterruptionFrame

from ubo_assistant.ubo_output_transport import UboOutputTransport


def _build() -> UboOutputTransport:
    """Construct a transport without invoking BaseOutputTransport's setup."""
    transport = UboOutputTransport.__new__(UboOutputTransport)
    transport.client = cast('Any', MagicMock())
    transport._assistance_id = 'original-id'  # noqa: SLF001
    transport._audio_assistance_index = 42  # noqa: SLF001
    transport._video_assistance_index = 17  # noqa: SLF001
    transport._resamplers = {}  # noqa: SLF001
    return transport


class UboOutputTransportInterruptionTests(unittest.IsolatedAsyncioTestCase):
    """Behavioural tests for the interruption-reset hook."""

    async def test_interruption_frame_resets_id_and_indices(self) -> None:
        """InterruptionFrame must mint a new id and reset both indices to 0."""
        transport = _build()

        with patch.object(
            UboOutputTransport.__mro__[1],
            '_handle_frame',
            new=AsyncMock(),
        ):
            await transport._handle_frame(InterruptionFrame())  # noqa: SLF001

        # New id assigned and indices reset; we don't pin the exact uuid value,
        # just that it changed.
        assert transport._assistance_id != 'original-id'  # noqa: SLF001, S101
        assert transport._audio_assistance_index == 0  # noqa: SLF001, S101
        assert transport._video_assistance_index == 0  # noqa: SLF001, S101

    async def test_repeated_interruptions_keep_resetting(self) -> None:
        """Each InterruptionFrame mints a fresh id; previous id is discarded."""
        transport = _build()

        with patch.object(
            UboOutputTransport.__mro__[1],
            '_handle_frame',
            new=AsyncMock(),
        ):
            await transport._handle_frame(InterruptionFrame())  # noqa: SLF001
            first_id = transport._assistance_id  # noqa: SLF001

            # Pretend the next utterance produced some audio.
            transport._audio_assistance_index = 7  # noqa: SLF001
            await transport._handle_frame(InterruptionFrame())  # noqa: SLF001

        assert transport._assistance_id != first_id  # noqa: SLF001, S101
        assert transport._audio_assistance_index == 0  # noqa: SLF001, S101


class UboOutputTransportNonInterruptionTests(unittest.IsolatedAsyncioTestCase):
    """Non-interruption frames must not touch the id/indices."""

    async def test_non_interruption_frame_leaves_id_and_indices_untouched(
        self,
    ) -> None:
        """Generic frames go to super() and don't reset the assistance state."""
        from pipecat.frames.frames import StartFrame

        transport = _build()
        original_id = transport._assistance_id  # noqa: SLF001
        original_audio_index = transport._audio_assistance_index  # noqa: SLF001
        original_video_index = transport._video_assistance_index  # noqa: SLF001

        with patch.object(
            UboOutputTransport.__mro__[1],
            '_handle_frame',
            new=AsyncMock(),
        ):
            # StartFrame is not an InterruptionFrame nor OutputAudioRawFrame —
            # falls through to super().
            await transport._handle_frame(  # noqa: SLF001
                StartFrame.__new__(StartFrame),
            )

        assert transport._assistance_id == original_id  # noqa: SLF001, S101
        assert transport._audio_assistance_index == original_audio_index  # noqa: SLF001, S101
        assert transport._video_assistance_index == original_video_index  # noqa: SLF001, S101


if __name__ == '__main__':
    unittest.main()

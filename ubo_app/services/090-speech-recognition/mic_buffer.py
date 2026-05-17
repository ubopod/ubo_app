"""Rolling microphone buffer with on-demand WAV dump.

Holds the most recent ``duration_seconds`` of raw mic audio in memory; on
demand (e.g. when an assistant wake phrase or stop-talking phrase is heard)
writes the buffer to a timestamped WAV file under ``output_dir`` so the
phrase + immediate audio context can be reviewed offline.
"""

from __future__ import annotations

import re
import wave
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ubo_app.logger import logger

if TYPE_CHECKING:
    from pathlib import Path

    from ubo_app.store.services.audio import AudioSample


_SLUG_CHARS = re.compile(r'[^a-z0-9]+')


def _slugify(phrase: str) -> str:
    """Filesystem-safe slug for a wake phrase (lowercase, no punctuation)."""
    return _SLUG_CHARS.sub('-', phrase.strip().lower()).strip('-') or 'phrase'


class MicBuffer:
    """Rolling buffer of the last ``duration_seconds`` of microphone audio."""

    def __init__(
        self,
        *,
        duration_seconds: float,
        output_dir: Path,
    ) -> None:
        """Configure buffer window length and dump location."""
        self._duration = duration_seconds
        self._output_dir = output_dir
        self._buffer: deque[tuple[float, AudioSample]] = deque()

    def add(self, timestamp: float, sample: AudioSample) -> None:
        """Append a new sample and prune entries older than the window."""
        self._buffer.append((timestamp, sample))
        cutoff = timestamp - self._duration
        while self._buffer and self._buffer[0][0] < cutoff:
            self._buffer.popleft()

    def dump(self, phrase: str) -> Path | None:
        """Write the current buffer to a WAV file. Returns the written path."""
        if not self._buffer:
            logger.debug(
                'MicBuffer.dump skipped: buffer is empty',
                extra={'phrase': phrase},
            )
            return None

        entries = list(self._buffer)
        first_sample = entries[0][1]

        self._output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime('%Y-%m-%dT%H%M%S')
        path = self._output_dir / f'{_slugify(phrase)}_{timestamp}.wav'

        try:
            with wave.open(str(path), 'wb') as wf:
                wf.setnchannels(first_sample.channels)
                wf.setsampwidth(first_sample.width)
                wf.setframerate(first_sample.rate)
                for _, sample in entries:
                    wf.writeframes(sample.data)
        except OSError:
            logger.exception(
                'MicBuffer.dump failed to write WAV file',
                extra={'path': str(path), 'phrase': phrase},
            )
            return None

        logger.info(
            'MicBuffer dumped wake-phrase audio context',
            extra={
                'path': str(path),
                'phrase': phrase,
                'sample_count': len(entries),
            },
        )
        return path

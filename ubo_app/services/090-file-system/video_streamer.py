"""Video frame streamer for file system preview."""

from __future__ import annotations

import subprocess
import threading
from typing import TYPE_CHECKING

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.audio import (
    AudioPlayAudioSampleAction,
    AudioSample,
    AudioStopPlaybackAction,
)
from ubo_app.store.services.file_system import FileSystemVideoFrameEvent

if TYPE_CHECKING:
    from collections.abc import Callable

PREVIEW_WIDTH = 240
PREVIEW_HEIGHT = 240
FRAME_INTERVAL = 1 / 15  # 15 fps for preview

AUDIO_RATE = 22050
AUDIO_CHANNELS = 1
AUDIO_WIDTH = 2  # 16-bit PCM
AUDIO_CHUNK_SECONDS = 2  # Send audio in 2-second chunks to avoid flooding

# Track the active streaming session so it can be stopped.
_active_session: list[_VideoSession | None] = [None]


class _VideoSession:
    """Manages a video streaming session lifecycle."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.is_running = True
        self._video_thread: threading.Thread | None = None
        self._audio_thread: threading.Thread | None = None
        self._audio_process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        """Start video and audio streaming in daemon threads."""
        self._video_thread = threading.Thread(
            target=self._stream_frames,
            name=f'video-stream:{self.path}',
            daemon=True,
        )
        self._video_thread.start()

        self._audio_thread = threading.Thread(
            target=self._stream_audio,
            name=f'audio-stream:{self.path}',
            daemon=True,
        )
        self._audio_thread.start()

    def stop(self) -> None:
        """Stop the streaming session."""
        self.is_running = False
        if self._audio_process is not None:
            self._audio_process.terminate()

    def _stream_audio(self) -> None:
        """Extract and stream audio from the video file using ffmpeg."""
        try:
            self._audio_process = subprocess.Popen(  # noqa: S603
                [  # noqa: S607
                    'ffmpeg',
                    '-i',
                    self.path,
                    '-vn',
                    '-f',
                    's16le',
                    '-acodec',
                    'pcm_s16le',
                    '-ar',
                    str(AUDIO_RATE),
                    '-ac',
                    str(AUDIO_CHANNELS),
                    '-',
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.warning('ffmpeg not found, video audio will not play')
            return

        stdout = self._audio_process.stdout
        if stdout is None:
            return

        # Send audio in larger chunks to avoid flooding the store/logs
        chunk_size = AUDIO_RATE * AUDIO_CHANNELS * AUDIO_WIDTH * AUDIO_CHUNK_SECONDS

        import time

        try:
            while self.is_running:
                data = stdout.read(chunk_size)
                if not data:
                    break
                store.dispatch(
                    AudioPlayAudioSampleAction(
                        sample=AudioSample(
                            data=data,
                            channels=AUDIO_CHANNELS,
                            rate=AUDIO_RATE,
                            width=AUDIO_WIDTH,
                        ),
                    ),
                )
                # Wait for the chunk duration before reading the next one
                # so we don't flood the store with queued-up audio
                time.sleep(
                    len(data) / (AUDIO_RATE * AUDIO_CHANNELS * AUDIO_WIDTH),
                )
        finally:
            stdout.close()
            self._audio_process.terminate()
            self._audio_process.wait()
            self._audio_process = None

    def _stream_frames(self) -> None:
        """Decode and stream video frames."""
        import time

        import cv2
        import numpy as np

        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            logger.warning(
                'Failed to open video file',
                extra={'path': self.path},
            )
            return

        try:
            while self.is_running:
                ret, frame = cap.read()
                if not ret:
                    break

                # Resize to preview resolution
                h, w = frame.shape[:2]
                scale = min(PREVIEW_WIDTH / w, PREVIEW_HEIGHT / h)
                new_w = int(w * scale)
                new_h = int(h * scale)
                frame = cv2.resize(frame, (new_w, new_h))

                # Convert BGR (OpenCV) to RGB
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Ensure contiguous array for tobytes
                frame = np.ascontiguousarray(frame)

                store._dispatch(  # noqa: SLF001
                    [
                        FileSystemVideoFrameEvent(
                            data=frame.tobytes(),
                            width=new_w,
                            height=new_h,
                        ),
                    ],
                )

                time.sleep(FRAME_INTERVAL)
        finally:
            cap.release()


def start_video_stream(path: str) -> None:
    """Start streaming video frames for the given file path."""
    stop_video_stream()
    session = _VideoSession(path)
    _active_session[0] = session
    session.start()


def stop_video_stream() -> None:
    """Stop any active video streaming session."""
    session = _active_session[0]
    if session is not None:
        session.stop()
        _active_session[0] = None
        store.dispatch(AudioStopPlaybackAction())


def register_video_stream_cleanup() -> Callable[[], None]:
    """Subscribe to stack changes to stop streaming when viewer is closed."""
    from ubo_app.store.core.types import StackChangedEvent

    def _handle_stack_changed(event: StackChangedEvent) -> None:
        from ubo_app.store.core.types.stack_items import ApplicationStackItem

        has_viewer = any(
            isinstance(item, ApplicationStackItem)
            and item.application_id == 'ubo:video-viewer'
            for item in event.stack
        )
        if not has_viewer:
            stop_video_stream()

    return store.subscribe_event(StackChangedEvent, _handle_stack_changed)

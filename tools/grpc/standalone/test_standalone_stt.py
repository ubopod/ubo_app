"""Test standalone STT: send WAV audio, get transcribed text.

Usage::

    python tools/grpc/standalone/test_standalone_stt.py [--host HOST] [--port PORT] \
        [--provider PROVIDER] audio.wav

Prerequisites: core running with gRPC enabled + assistant service running.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import wave

from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistantHandleReportEvent,
    AssistantSttName,
    AssistantTranscribeAction,
    Event,
)

logger = logging.getLogger(__name__)

STT_PROVIDERS = {
    name.lower(): member
    for name, member in AssistantSttName.__members__.items()
    if member.value != 0
}


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Test standalone STT over gRPC',
    )
    parser.add_argument('audio_file', help='Path to WAV file')
    parser.add_argument(
        '--host',
        default='127.0.0.1',
        help='gRPC host (default: 127.0.0.1)',
    )
    parser.add_argument(
        '--port',
        type=int,
        default=50051,
        help='gRPC port (default: 50051)',
    )
    parser.add_argument(
        '--provider',
        default='vosk',
        help=(
            'STT provider (default: vosk). '
            f'Options: {", ".join(STT_PROVIDERS)}'
        ),
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=30.0,
        help='Timeout in seconds (default: 30)',
    )
    return parser.parse_args()


def _read_wav(path: str) -> tuple[bytes, int, int]:
    """Read a WAV file and return (pcm_bytes, sample_rate, num_channels)."""
    with wave.open(path, 'rb') as wf:
        pcm = wf.readframes(wf.getnframes())
        return pcm, wf.getframerate(), wf.getnchannels()


def _get_active_field(data: AcceptableAssistanceFrame) -> str | None:
    """Return the name of the active oneof field, if any."""
    group = getattr(data, '_group_current', {})
    return next(iter(group.values()), None)


def _handle_text_frame(
    data: AcceptableAssistanceFrame,
    session_id: str,
    done: asyncio.Event,
    collected_text: list[str],
) -> None:
    """Handle an incoming text frame from the STT service."""
    frame = data.assistance_text_frame
    if frame.session_id != session_id:
        return
    if frame.text:
        collected_text.append(frame.text)
        logger.info('  [chunk %d] %s', frame.index, frame.text)
    if frame.is_last_frame:
        done.set()


def _handle_error_frame(
    data: AcceptableAssistanceFrame,
    session_id: str,
    done: asyncio.Event,
) -> None:
    """Handle an incoming error frame."""
    frame = data.assistance_error_frame
    if frame.session_id != session_id:
        return
    logger.error('STT error: %s', frame.error)
    done.set()


async def _run(args: argparse.Namespace) -> None:
    """Execute the STT test with parsed arguments."""
    provider = STT_PROVIDERS.get(args.provider.lower())
    if provider is None:
        logger.error(
            'Unknown provider: %s. Options: %s',
            args.provider,
            ', '.join(STT_PROVIDERS),
        )
        sys.exit(1)

    pcm_bytes, sample_rate, num_channels = _read_wav(args.audio_file)
    logger.info(
        'Read %d bytes from %s (rate=%d, channels=%d)',
        len(pcm_bytes),
        args.audio_file,
        sample_rate,
        num_channels,
    )

    session_id = f'test-stt-{asyncio.get_event_loop().time():.0f}'
    done = asyncio.Event()
    collected_text: list[str] = []
    client = UboRPCClient(host=args.host, port=args.port)

    def on_report(event: Event) -> None:
        report = event.assistant_handle_report_event
        if not report:
            return
        active = _get_active_field(report.data)
        if active == 'assistance_text_frame':
            _handle_text_frame(
                report.data,
                session_id,
                done,
                collected_text,
            )
        elif active == 'assistance_error_frame':
            _handle_error_frame(report.data, session_id, done)

    unsubscribe = client.subscribe_event(
        event_type=Event(
            assistant_handle_report_event=AssistantHandleReportEvent(),
        ),
        callback=on_report,
    )

    logger.info(
        'Dispatching (provider=%s, session=%s)',
        args.provider,
        session_id,
    )
    client.dispatch(
        action=Action(
            assistant_transcribe_action=AssistantTranscribeAction(
                audio=pcm_bytes,
                session_id=session_id,
                sample_rate=sample_rate,
                num_channels=num_channels,
                stt_provider=provider,
            ),
        ),
    )

    try:
        await asyncio.wait_for(done.wait(), timeout=args.timeout)
    except TimeoutError:
        logger.exception('Timed out after %ss', args.timeout)
        sys.exit(1)
    finally:
        unsubscribe()
        client.close()

    logger.info('Transcription: %s', ' '.join(collected_text))


async def main() -> None:
    """Entry point for the standalone STT test."""
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    await _run(_parse_args())


if __name__ == '__main__':
    asyncio.run(main())

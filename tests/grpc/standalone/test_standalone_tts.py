"""Test standalone TTS: send text, save synthesized audio to WAV.

Usage::

    python test_standalone_tts.py [--host HOST] [--port PORT] \
        [--provider PROVIDER] [--output out.wav] "text to speak"

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
    AssistantSynthesizeAction,
    AssistantTtsName,
    Event,
)

logger = logging.getLogger(__name__)

TTS_PROVIDERS = {
    name.lower(): member
    for name, member in AssistantTtsName.__members__.items()
    if member.value != 0
}


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Test standalone TTS over gRPC',
    )
    parser.add_argument('text', help='Text to synthesize')
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
        default='piper',
        help=(
            'TTS provider (default: piper). '
            f'Options: {", ".join(TTS_PROVIDERS)}'
        ),
    )
    parser.add_argument(
        '--output',
        '-o',
        default='output.wav',
        help='Output WAV file (default: output.wav)',
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=30.0,
        help='Timeout in seconds (default: 30)',
    )
    return parser.parse_args()


def _get_active_field(data: AcceptableAssistanceFrame) -> str | None:
    """Return the name of the active oneof field, if any."""
    group = getattr(data, '_group_current', {})
    return next(iter(group.values()), None)


def _save_wav(
    path: str,
    audio: bytes,
    rate: int,
    channels: int,
    sample_width: int,
) -> None:
    """Write raw PCM audio to a WAV file."""
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(audio)


def _handle_audio_frame(
    data: AcceptableAssistanceFrame,
    session_id: str,
    audio_chunks: list[bytes],
    audio_params: dict[str, int],
) -> None:
    """Handle an incoming audio frame from the TTS service."""
    frame = data.assistance_audio_frame
    if frame.session_id != session_id:
        return
    if not (frame.audio and frame.audio.data):
        return
    audio_chunks.append(frame.audio.data)
    if not audio_params:
        audio_params['rate'] = frame.audio.rate
        audio_params['channels'] = frame.audio.channels
        audio_params['width'] = frame.audio.width
    logger.info(
        '  [chunk %d] %d bytes',
        frame.index,
        len(frame.audio.data),
    )


def _handle_text_frame(
    data: AcceptableAssistanceFrame,
    session_id: str,
    done: asyncio.Event,
) -> None:
    """Handle an incoming text frame (used for end-of-stream signal)."""
    frame = data.assistance_text_frame
    if frame.session_id != session_id:
        return
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
    logger.error('TTS error: %s', frame.error)
    done.set()


async def _run(args: argparse.Namespace) -> None:
    """Execute the TTS test with parsed arguments."""
    provider = TTS_PROVIDERS.get(args.provider.lower())
    if provider is None:
        logger.error(
            'Unknown provider: %s. Options: %s',
            args.provider,
            ', '.join(TTS_PROVIDERS),
        )
        sys.exit(1)

    session_id = f'test-tts-{asyncio.get_event_loop().time():.0f}'
    done = asyncio.Event()
    audio_chunks: list[bytes] = []
    audio_params: dict[str, int] = {}
    client = UboRPCClient(host=args.host, port=args.port)

    def on_report(event: Event) -> None:
        report = event.assistant_handle_report_event
        if not report:
            return
        active = _get_active_field(report.data)
        if active == 'assistance_audio_frame':
            _handle_audio_frame(
                report.data,
                session_id,
                audio_chunks,
                audio_params,
            )
        elif active == 'assistance_text_frame':
            _handle_text_frame(report.data, session_id, done)
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
            assistant_synthesize_action=AssistantSynthesizeAction(
                text=args.text,
                session_id=session_id,
                tts_provider=provider,
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

    if not audio_chunks:
        logger.error('No audio data received.')
        sys.exit(1)

    all_audio = b''.join(audio_chunks)
    rate = audio_params.get('rate', 16000)
    channels = audio_params.get('channels', 1)
    sample_width = audio_params.get('width', 2)

    _save_wav(args.output, all_audio, rate, channels, sample_width)

    duration = len(all_audio) / (rate * channels * sample_width)
    logger.info(
        'Saved %d bytes (%.1fs) to %s',
        len(all_audio),
        duration,
        args.output,
    )


async def main() -> None:
    """Entry point for the standalone TTS test."""
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    await _run(_parse_args())


if __name__ == '__main__':
    asyncio.run(main())

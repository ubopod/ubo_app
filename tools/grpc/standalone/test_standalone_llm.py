"""Test standalone LLM: send prompt, get streamed response.

Usage::

    python tools/grpc/standalone/test_standalone_llm.py [--host HOST] [--port PORT] \
        [--provider PROVIDER] [--system "prompt"] "user message"

Prerequisites: core running with gRPC enabled + assistant service running.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    AcceptableAssistanceFrame,
    Action,
    AssistantCompleteAction,
    AssistantHandleReportEvent,
    AssistantLlmName,
    Event,
)

logger = logging.getLogger(__name__)

LLM_PROVIDERS = {
    name.lower(): member
    for name, member in AssistantLlmName.__members__.items()
    if member.value != 0
}


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Test standalone LLM over gRPC',
    )
    parser.add_argument('text', help='User message / prompt')
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
        default='ollama',
        help=(
            'LLM provider (default: ollama). '
            f'Options: {", ".join(LLM_PROVIDERS)}'
        ),
    )
    parser.add_argument(
        '--system',
        default=None,
        help='System prompt (optional)',
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=60.0,
        help='Timeout in seconds (default: 60)',
    )
    return parser.parse_args()


def _get_active_field(data: AcceptableAssistanceFrame) -> str | None:
    """Return the name of the active oneof field, if any."""
    group = getattr(data, '_group_current', {})
    return next(iter(group.values()), None)


def _handle_text_frame(
    data: AcceptableAssistanceFrame,
    session_id: str,
    done: asyncio.Event,
) -> None:
    """Handle an incoming text frame from the LLM."""
    frame = data.assistance_text_frame
    if frame.session_id != session_id:
        return
    if frame.text:
        sys.stdout.write(frame.text)
        sys.stdout.flush()
    if frame.is_last_frame:
        sys.stdout.write('\n')
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
    logger.error('LLM error: %s', frame.error)
    done.set()


async def _run(args: argparse.Namespace) -> None:
    """Execute the LLM test with parsed arguments."""
    provider = LLM_PROVIDERS.get(args.provider.lower())
    if provider is None:
        logger.error(
            'Unknown provider: %s. Options: %s',
            args.provider,
            ', '.join(LLM_PROVIDERS),
        )
        sys.exit(1)

    session_id = f'test-llm-{asyncio.get_event_loop().time():.0f}'
    done = asyncio.Event()
    client = UboRPCClient(host=args.host, port=args.port)

    def on_report(event: Event) -> None:
        report = event.assistant_handle_report_event
        if not report:
            return
        active = _get_active_field(report.data)
        if active == 'assistance_text_frame':
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
            assistant_complete_action=AssistantCompleteAction(
                text=args.text,
                session_id=session_id,
                llm_provider=provider,
                system_prompt=args.system,
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


async def main() -> None:
    """Entry point for the standalone LLM test."""
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    await _run(_parse_args())


if __name__ == '__main__':
    asyncio.run(main())

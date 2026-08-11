"""Surface live-pipeline provider errors as on-device notifications.

When a provider API in the live assistant pipeline fails (e.g. an LLM
returning HTTP ``402 Insufficient Balance``, a bad key ``401``, a ``429``
rate-limit, or a ``5xx`` server error), pipecat only logs the failure and the
assistant goes silent. :func:`attach_error_notifier` hooks the worker-level
``on_pipeline_error`` event and dispatches a flash notification so the user
knows which stage failed and why.

Not every ``ErrorFrame`` deserves a notification, though: websocket-based
providers emit one whenever the far end drops an idle connection, even though
pipecat immediately reconnects. :func:`is_transient_error` filters those out.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from loguru import logger
from ubo_bindings.ubo.v1 import (
    Action,
    Chime,
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from websockets.exceptions import ConnectionClosed
from websockets.frames import CloseCode

if TYPE_CHECKING:
    from pipecat.frames.frames import ErrorFrame
    from pipecat.pipeline.worker import PipelineWorker
    from ubo_bindings.client import UboRPCClient


_ERROR_ICON = '󰀦'
"""Same warning glyph the assistant reducer uses for failures."""

_THROTTLE_SECONDS = 10.0
"""Suppress identical provider errors within this window to avoid spam."""

_STATUS_CODE_PATTERN = re.compile(
    r'(?:error code|status(?:[ _]code)?|http)\D{0,4}(\d{3})',
    re.IGNORECASE,
)
# The message value is delimited by whichever quote the provider used; it
# commonly contains the *other* quote (e.g. ``"The model 'dall-e-3' does not
# exist."``). Capture the opening quote and stop at the matching closing quote
# so inner quotes don't truncate the message.
_PROVIDER_MESSAGE_PATTERN = re.compile(
    r"['\"]message['\"]\s*:\s*(?P<quote>['\"])(?P<message>.*?)(?P=quote)",
)

_CODE_MESSAGES = {
    401: 'Authentication failed — check the API key.',
    403: 'Authentication failed — check the API key.',
    402: 'Insufficient balance or credit on your provider account.',
    429: 'Rate limit exceeded — try again shortly.',
}

# Recoverable streaming-teardown errors that are NOT worth a user notification.
# Streaming providers hold a websocket open across the whole session; the far end
# eventually drops it (idle timeout, server restart, upstream hiccup). Pipecat's
# ``WebsocketService`` reconnects automatically, so by the time the ``ErrorFrame``
# reaches us the connection is usually already healthy again — the frame is a
# teardown artifact of a *successful* recovery, not a failure the user can act on.
#
# Two tiers, because pipecat populates ``ErrorFrame.exception`` inconsistently:
#
# 1. Typed (preferred) — the close code off a ``ConnectionClosed``. This is the
#    formal, RFC 6455 vocabulary; see ``_TRANSIENT_CLOSE_CODES``.
# 2. Signature match — for the sites that call ``push_error(error_msg=...)`` with
#    no ``exception=`` (e.g. Mistral realtime STT's idle "timeout waiting for
#    response"), leaving only the rendered message to go on.
#
# Genuine failures are unaffected. When a reconnect really cannot be re-established
# pipecat reports it with distinct wording that matches neither tier —
# "reconnection attempt N failed", "failed to reconnect after N attempts",
# "connection failed N times immediately after connecting", "websocket
# unavailable" — and auth/balance/config errors carry a status code instead.
_TRANSIENT_ERROR_PATTERN = re.compile(
    r'timeout waiting for response'
    r'|received 1011'
    r'|1011 \(internal error\)'
    r'|upstream connection error',
    re.IGNORECASE,
)

# Close codes meaning "the transport dropped / the server is having a moment"
# rather than "the provider rejected this request". Retrying is the correct
# response to all of them, so none are user-actionable. The request-rejection
# codes (1002 protocol error, 1003/1007 bad data, 1008 policy violation, 1009
# message too big, 1010 mandatory extension, 1015 TLS) are deliberately absent —
# those point at a real misconfiguration and must still notify.
#
# 1001 covers the same idle-socket recycling as 1006, just announced politely:
# ElevenLabs retires an idle connection either by dropping it outright (1006) or
# by completing the handshake with "going away" (1001), and which one you get is
# the server's choice, not a property of the request.
_TRANSIENT_CLOSE_CODES = frozenset({
    CloseCode.GOING_AWAY,  # 1001 — far end is cycling the connection
    CloseCode.ABNORMAL_CLOSURE,  # 1006 — connection lost with no close handshake
    CloseCode.INTERNAL_ERROR,  # 1011
    CloseCode.SERVICE_RESTART,  # 1012
    CloseCode.TRY_AGAIN_LATER,  # 1013
    CloseCode.BAD_GATEWAY,  # 1014
})


def is_transient_error(frame: ErrorFrame) -> bool:
    """Return True for recoverable streaming-teardown errors not worth notifying."""
    exception = frame.exception
    if isinstance(exception, ConnectionClosed):
        close = exception.rcvd or exception.sent
        # Neither side sent a close frame → abnormal closure by definition.
        code = CloseCode.ABNORMAL_CLOSURE if close is None else close.code
        return code in _TRANSIENT_CLOSE_CODES
    return bool(_TRANSIENT_ERROR_PATTERN.search(frame.error or ''))

# Substrings of the originating processor's class name → user-facing stage
# label. Provider services are named e.g. ``DeepSeekLLMService``,
# ``DeepgramSTTService``, ``ElevenLabsTTSService`` (and our wrappers
# ``UboLLMService`` etc.). The ``…Service`` suffix is matched as part of the
# needle because the bare ``STT``/``TTS`` tokens overlap incidentally —
# ``ELEVENLABSTTSSERVICE`` contains ``STT`` and ``DEEPGRAMSTTSERVICE``
# contains ``TTS`` — which would misclassify the stage.
_STAGE_LABELS = (
    ('LLMSERVICE', 'Language model'),
    ('STTSERVICE', 'Speech-to-text'),
    ('TTSSERVICE', 'Text-to-speech'),
    ('IMAGE', 'Image generator'),
    ('LLM', 'Language model'),
)

_MAX_CONTENT_LENGTH = 120


class ErrorNotification(NamedTuple):
    """User-facing title/content derived from a pipeline ``ErrorFrame``."""

    title: str
    content: str


def _stage_label(processor: object | None) -> str:
    name = type(processor).__name__.upper() if processor is not None else ''
    for needle, label in _STAGE_LABELS:
        if needle in name:
            return label
    return 'Assistant'


def _extract_status_code(error: str) -> int | None:
    match = _STATUS_CODE_PATTERN.search(error)
    return int(match.group(1)) if match else None


def _provider_message(error: str) -> str:
    match = _PROVIDER_MESSAGE_PATTERN.search(error)
    message = match.group('message').strip() if match else error.strip()
    if len(message) > _MAX_CONTENT_LENGTH:
        message = message[: _MAX_CONTENT_LENGTH - 1].rstrip() + '…'
    return message or 'The provider reported an error.'


def classify_error(frame: ErrorFrame) -> ErrorNotification:
    """Map an ``ErrorFrame`` to a friendly notification title and content."""
    stage = _stage_label(frame.processor)
    error = frame.error or ''
    code = _extract_status_code(error)

    if code in _CODE_MESSAGES:
        content = _CODE_MESSAGES[code]
    elif code is not None and 500 <= code < 600:  # noqa: PLR2004
        content = 'The provider had a server error — try again later.'
    else:
        content = _provider_message(error)

    return ErrorNotification(title=f'{stage} provider error', content=content)


def attach_error_notifier(worker: PipelineWorker, client: UboRPCClient) -> None:
    """Notify the user when the live pipeline emits an ``ErrorFrame``."""
    # Closure-scoped throttle: last dispatch time keyed by the rendered
    # (title, content) so a repeated identical error is suppressed while a
    # different failure still gets through.
    last_dispatched: dict[ErrorNotification, float] = {}

    @worker.event_handler('on_pipeline_error')
    async def _on_pipeline_error(_worker: PipelineWorker, frame: ErrorFrame) -> None:
        if is_transient_error(frame):
            # Recoverable streaming-teardown noise (e.g. Mistral realtime STT
            # idle timeout / 1011 upstream close) — log, but don't notify.
            logger.debug(
                'Suppressing transient provider-error notification {extra}',
                extra={'error': frame.error},
            )
            return

        notification = classify_error(frame)

        now = client.event_loop.time()
        previous = last_dispatched.get(notification)
        if previous is not None and now - previous < _THROTTLE_SECONDS:
            return
        last_dispatched[notification] = now

        logger.info(
            'Dispatching provider-error notification {extra}',
            extra={'title': notification.title, 'content': notification.content},
        )
        client.dispatch(
            action=Action(
                notifications_add_action=NotificationsAddAction(
                    # Stable per-stage id so a repeated error updates the same
                    # notification in place instead of stacking the UI.
                    notification=Notification(
                        id=f'assistant-provider-error:{notification.title}',
                        title=notification.title,
                        content=notification.content,
                        importance=Importance.HIGH,
                        chime=Chime.FAILURE,
                        icon=_ERROR_ICON,
                        display_type=NotificationDisplayType.FLASH,
                    ),
                ),
            ),
        )

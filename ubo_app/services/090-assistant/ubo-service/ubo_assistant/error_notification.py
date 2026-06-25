"""Surface live-pipeline provider errors as on-device notifications.

When a provider API in the live assistant pipeline fails (e.g. an LLM
returning HTTP ``402 Insufficient Balance``, a bad key ``401``, a ``429``
rate-limit, or a ``5xx`` server error), pipecat only logs the failure and the
assistant goes silent. :func:`attach_error_notifier` hooks the worker-level
``on_pipeline_error`` event and dispatches a flash notification so the user
knows which stage failed and why.
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
# Realtime STT providers (e.g. Mistral Voxtral) hold a websocket open; once the
# user stops speaking and the session goes idle, the connection times out
# waiting for a response, or the upstream closes it with a ``1011`` internal
# error. The transcription has already completed, so these are non-actionable
# teardown artifacts — still logged, but suppressed from the notification path
# so they don't spam the device after every interaction. Genuine errors (auth,
# balance, bad config) don't match these signatures and still notify.
_TRANSIENT_ERROR_PATTERN = re.compile(
    r'timeout waiting for response'
    r'|received 1011'
    r'|1011 \(internal error\)'
    r'|upstream connection error',
    re.IGNORECASE,
)


def is_transient_error(frame: ErrorFrame) -> bool:
    """Return True for recoverable streaming-teardown errors not worth notifying."""
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

# ruff: noqa: D100, D103
from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncio import Handle

    from ubo_handle import ReducerRegistrar, register

    from ubo_app.store.services.assistant import AssistantHandleReportEvent
    from ubo_app.store.services.chat import (
        ChatSessionEndedEvent,
        ChatUserMessageSentEvent,
    )


# How long after the last activity to close the chat overlay, provided
# the assistant is not listening. "Activity" = any chat write, pipecat
# audio enqueue, or pipecat audio-playback-done — all stamped onto
# ``ChatState.last_activity_time`` by the chat reducer. The dismiss
# loop simply polls ``now - last_activity_time`` against this. Same
# pattern as ``DisplayState.last_activity_time`` + display blank timer.
_DISMISS_DELAY_SECONDS = 4.0
# Cadence at which the dismiss loop polls. Small enough that the perceived
# delay between "should close" and "actually closes" is negligible, large
# enough not to spam state reads.
_DISMISS_POLL_SECONDS = 0.5


@dataclass
class _VoiceState:
    """Runtime state for the assistant→chat voice handler.

    A module-level dataclass instance (per the no-globals rule) tracks the
    in-flight turn — *not* the dismiss timeout itself, which is driven by
    ``ChatState.last_activity_time`` + the periodic dismiss loop:

    - ``is_listening``: last observed ``state.assistant.is_listening`` value,
      used for rising/falling-edge detection in the autorun.
    - ``user_message_id`` / ``assistant_message_id``: the bubble id being
      streamed into for the current STT / LLM stream. Cleared on
      ``is_last_frame``.
    - ``dismiss_handle``: handle for the long-running dismiss-polling
      asyncio task, so it can be cancelled cleanly.
    - ``timer_initiated_dismiss``: set True just before our dismiss loop
      dispatches ``ChatEndSessionAction``. The session-ended handler uses
      it to suppress ``AssistantStopTalkingAction`` on the timeout path —
      by construction the assistant is already idle there, and
      dispatching it would broadcast an ``InterruptionFrame`` that cuts
      in-flight TTS. On the Back-button path this flag stays False and
      the handler stops the assistant cleanly.
    """

    is_listening: bool = False
    user_message_id: str = ''
    assistant_message_id: str = ''
    dismiss_handle: Handle | None = None
    timer_initiated_dismiss: bool = False


_voice_state = _VoiceState()


def _register_chat_menu_item() -> None:
    """Register a one-click "Chat" item under Settings → Assistant.

    Selecting it dispatches ``ChatStartSessionAction`` (via the action
    registry), which opens the chat overlay on every connected client.
    """
    from ubo_app.store.core.action_registry import register_action
    from ubo_app.store.core.types import (
        RegisterSettingAppAction,
        SettingsCategory,
    )
    from ubo_app.store.main import store
    from ubo_app.store.services.chat import ChatStartSessionAction

    def open_chat() -> None:
        store.dispatch(ChatStartSessionAction())

    register_action('chat:open', open_chat, allow_reregister=True)
    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=100,
            key='open',
            label='Chat',
            icon='󰭹',
            action_id='chat:open',
        ),
    )


def _register_echo_handler() -> None:
    """Echo every sent user message back as an assistant reply.

    Test-only scaffolding (gated behind ``IS_TEST_ENV`` in ``setup``): it
    stands in for the phase-2 assistant responder so the chat widget can be
    exercised end-to-end without the STT/LLM/TTS stack. It must not run
    alongside the real responder — both subscribe to
    ``ChatUserMessageSentEvent`` and would each reply.
    """
    from ubo_app.logger import logger
    from ubo_app.store.main import store
    from ubo_app.store.services.chat import (
        ChatAddMessageAction,
        ChatMessage,
        ChatMessageKind,
        ChatRole,
        ChatUserMessageSentEvent,
    )

    def on_user_message(event: ChatUserMessageSentEvent) -> None:
        logger.info('[chat] received: %s', event.text)
        store.dispatch(
            ChatAddMessageAction(
                message=ChatMessage(
                    role=ChatRole.ASSISTANT,
                    kind=ChatMessageKind.TEXT,
                    text=f'echo=> {event.text}',
                ),
            ),
        )

    store.subscribe_event(ChatUserMessageSentEvent, on_user_message)


def _register_voice_handler() -> None:  # noqa: C901, PLR0915
    """Wire the pipecat assistant into the chat widget.

    This is the real assistant↔chat bridge (the echo handler is test-only
    scaffolding for the *typed* path). It opens the chat overlay when
    listening starts, mirrors STT/LLM text frames into chat bubbles, and
    stops the assistant when the chat is dismissed via Back.

    The idle auto-dismiss is **not** implemented here: the chat reducer
    stamps ``ChatState.last_activity_time`` on every chat write and on
    pipecat audio enqueue / playback-done, and a small polling task
    started here dispatches ``ChatEndSessionAction`` once that timestamp
    is older than ``_DISMISS_DELAY_SECONDS``. This mirrors the display
    backlight blank-timer (``services/000-display``) and means TTS audio
    that's still in the audio service's buffer keeps the chat open —
    the audio service dispatches ``AudioPlaybackDoneAction`` once its
    buffer drains, which is the authoritative "speaker has gone quiet"
    signal.
    """
    from ubo_app.store.main import store
    from ubo_app.store.services.assistant import (
        AssistanceTextFrame,
        AssistantHandleReportEvent,
        AssistantStopListeningAction,
        AssistantStopTalkingAction,
    )
    from ubo_app.store.services.chat import (
        ChatAddMessageAction,
        ChatAppendToMessageAction,
        ChatEndSessionAction,
        ChatMessage,
        ChatMessageKind,
        ChatRole,
        ChatSessionEndedEvent,
        ChatSetMessageTextAction,
        ChatStartSessionAction,
    )
    from ubo_app.utils.async_ import create_task

    # Live pipeline frames carry this ``source_id`` (see
    # ``ubo_assistant/ubo_output_transport.py`` and
    # ``ubo_assistant/switch.py``); one-shot programmatic requests use
    # ``'assistant_request'`` instead, which we deliberately ignore so
    # test/synthesis runs never hijack the chat overlay.
    live_pipeline_source_id = 'pipecat'

    def _selected_is_listening(state: object) -> bool:
        """Read ``state.assistant.is_listening`` defensively.

        The assistant service may not be loaded (some integration tests
        boot the chat service in isolation). In that case ``state.assistant``
        doesn't exist on the root state — treat it as "not listening" so the
        voice handler is a clean no-op.
        """
        assistant = getattr(state, 'assistant', None)
        if assistant is None:
            return False
        return bool(getattr(assistant, 'is_listening', False))

    @store.autorun(_selected_is_listening)
    def _on_listening_change(is_listening: bool) -> None:  # noqa: FBT001
        # Autorun callback signature is positional — the bool flag here is
        # the watched value, not a public API parameter.
        if is_listening and not _voice_state.is_listening:
            _voice_state.is_listening = True
            _voice_state.user_message_id = ''
            _voice_state.assistant_message_id = ''
            store.dispatch(ChatStartSessionAction())
        elif not is_listening and _voice_state.is_listening:
            _voice_state.is_listening = False
            # No timer to arm: ``ChatState.last_activity_time`` and the
            # background dismiss loop handle the countdown.

    def _route_stt_frame(frame: AssistanceTextFrame) -> None:
        # STT interim frames are cumulative — overwrite, never append.
        if not _voice_state.user_message_id:
            message = ChatMessage(
                role=ChatRole.USER,
                kind=ChatMessageKind.TEXT,
                text=frame.text,
            )
            _voice_state.user_message_id = message.id
            store.dispatch(ChatAddMessageAction(message=message))
        else:
            store.dispatch(
                ChatSetMessageTextAction(
                    message_id=_voice_state.user_message_id,
                    text=frame.text,
                ),
            )
        if frame.is_last_frame:
            _voice_state.user_message_id = ''

    def _route_llm_frame(frame: AssistanceTextFrame) -> None:
        # LLM streaming frames are deltas — append.
        if not _voice_state.assistant_message_id:
            message = ChatMessage(
                role=ChatRole.ASSISTANT,
                kind=ChatMessageKind.TEXT,
                text=frame.text,
            )
            _voice_state.assistant_message_id = message.id
            store.dispatch(ChatAddMessageAction(message=message))
        else:
            store.dispatch(
                ChatAppendToMessageAction(
                    message_id=_voice_state.assistant_message_id,
                    chunk=frame.text,
                ),
            )
        if frame.is_last_frame:
            _voice_state.assistant_message_id = ''

    def _on_report(event: AssistantHandleReportEvent) -> None:
        if event.source_id != live_pipeline_source_id:
            return
        frame = event.data
        # Audio frames keep the chat open via the reducer (which sees the
        # ``AudioPlayAudioSequenceAction`` dispatched by ``_communicate``);
        # the handler only routes text frames into chat bubbles.
        if not isinstance(frame, AssistanceTextFrame):
            return
        if frame.source == 'stt':
            _route_stt_frame(frame)
        elif frame.source == 'llm':
            _route_llm_frame(frame)

    def _on_session_ended(_event: ChatSessionEndedEvent) -> None:
        # See ``_VoiceState.timer_initiated_dismiss`` — only the Back-
        # button (and other external dismiss) path stops the assistant;
        # the auto-dismiss-timeout path leaves it alone.
        was_timer_dismiss = _voice_state.timer_initiated_dismiss
        _voice_state.timer_initiated_dismiss = False
        _voice_state.user_message_id = ''
        _voice_state.assistant_message_id = ''
        if not was_timer_dismiss:
            store.dispatch(AssistantStopListeningAction())
            store.dispatch(AssistantStopTalkingAction())

    async def _dismiss_loop() -> None:
        """Poll ``ChatState.last_activity_time`` and auto-dismiss when stale.

        Same shape as the display-blank inactivity monitor: small fixed
        cadence, read the relevant slice of state, dispatch if the gap
        exceeds the timeout and we're not currently listening.
        """
        while True:
            try:
                await asyncio.sleep(_DISMISS_POLL_SECONDS)
            except asyncio.CancelledError:
                return
            try:
                state = store._state  # noqa: SLF001
                if state is None:
                    continue
                chat = getattr(state, 'chat', None)
                if chat is None or not chat.is_active:
                    continue
                if chat.last_activity_time is None:
                    continue
                if _voice_state.is_listening:
                    continue
                # Never dismiss while pipecat TTS audio is actually being
                # played out — the reducer holds this flag True between
                # the first ``AudioPlayAudioSequenceAction`` (chunk queued)
                # and the matching ``AudioPlaybackDoneAction`` (audio
                # service's play loop exited because the buffer drained).
                if chat.is_audio_playing:
                    continue
                now = datetime.datetime.now(tz=datetime.UTC).timestamp()
                if now - chat.last_activity_time < _DISMISS_DELAY_SECONDS:
                    continue
                # Mark the dispatch as "from our timer" so the session-
                # ended handler doesn't broadcast ``AssistantStopTalkingAction``
                # (which would cut audio that *just* finished — and is
                # pointless when the assistant is already idle).
                _voice_state.timer_initiated_dismiss = True
                store.dispatch(ChatEndSessionAction())
            except Exception:
                from ubo_app.logger import logger

                logger.exception('Chat dismiss loop iteration failed')

    # Suppress the "function not used" warning — the autorun decorator holds
    # the reference for us, but linters can't see that.
    _ = _on_listening_change

    store.subscribe_event(AssistantHandleReportEvent, _on_report)
    store.subscribe_event(ChatSessionEndedEvent, _on_session_ended)
    _voice_state.dismiss_handle = create_task(_dismiss_loop())


def setup(register_reducer: ReducerRegistrar) -> None:
    from reducer import reducer

    from ubo_app.utils import IS_TEST_ENV

    register_reducer(reducer)
    _register_chat_menu_item()
    _register_voice_handler()
    # The echo responder is dev/test scaffolding — register it only under
    # the test harness so it never collides with the real assistant
    # responder (the voice handler covers the voice path; the echo handler
    # only services the typed-text seam, ``ChatUserMessageSentEvent``).
    if IS_TEST_ENV:
        _register_echo_handler()


register(
    service_id='chat',
    label='Chat',
    setup=setup,
)

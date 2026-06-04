"""Tests for the chat service's voice handler — the assistant→chat bridge.

The handler is registered in ``090-chat/ubo_handle.py``:

- ``@store.autorun(...)`` on ``state.assistant.is_listening`` opens the chat
  session on rising edges.
- ``store.subscribe_event(AssistantHandleReportEvent, ...)`` mirrors STT
  (cumulative) frames as ``ChatSetMessageTextAction`` and LLM (delta) frames
  as ``ChatAppendToMessageAction``.
- ``store.subscribe_event(ChatSessionEndedEvent, ...)`` stops the assistant
  on dismiss — *only* when the dismiss came from outside the handler
  (Back button), not the timeout path.
- A background polling task watches ``ChatState.last_activity_time`` and
  dispatches ``ChatEndSessionAction`` once stale. The actual timeout
  behaviour is tested through the chat reducer (which stamps the
  timestamp on activity); here we just stand the wiring up.

These tests stand up a minimal **fake store** that mimics just enough redux
to drive the handler: subscriptions, autorun edge firing, and dispatch
collection. This keeps the test fast and isolated — no chat reducer, no
assistant subprocess, no provider setup.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


class FakeStore:
    """Minimal in-memory stand-in for the redux store.

    Tracks what the handler dispatches, holds event subscriptions, and
    fires autorun callbacks when the watched value changes. Just enough to
    exercise ``_register_voice_handler``.
    """

    def __init__(self) -> None:
        """Set up empty dispatch log, subscription registry, and autorun list."""
        self.dispatched: list[Any] = []
        self._event_handlers: dict[type, list[Callable[[Any], None]]] = {}
        self._autoruns: list[
            tuple[Callable[[Any], Any], Callable[[Any], None], list[Any]]
        ] = []
        self._is_listening = False
        # The handler reads ``store._state`` from inside the dismiss loop;
        # expose a None default so it short-circuits during tests.
        self._state = None

    @property
    def _read_state(self) -> SimpleNamespace:
        return SimpleNamespace(
            assistant=SimpleNamespace(is_listening=self._is_listening),
        )

    def dispatch(self, action: Any) -> None:  # noqa: ANN401
        """Record a dispatched action. ``Any`` mirrors the real store's API."""
        self.dispatched.append(action)

    def subscribe_event(
        self,
        event_type: type,
        handler: Callable[[Any], None],
    ) -> Callable[[], None]:
        """Register an event handler keyed on its type.

        Returns an unsubscribe callable so the production code's cleanup
        path (the ``Subscriptions`` list returned by ``_register_voice_handler``)
        can detach the handler.
        """
        self._event_handlers.setdefault(event_type, []).append(handler)

        def _unsubscribe() -> None:
            handlers = self._event_handlers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

        return _unsubscribe

    def fire_event(self, event: Any) -> None:  # noqa: ANN401
        """Fan an event out to every subscriber synchronously."""
        for handler in self._event_handlers.get(type(event), []):
            handler(event)

    def autorun(
        self,
        selector: Callable[[Any], Any],
    ) -> Callable[[Callable[[Any], None]], Callable[[Any], None]]:
        """Mimic ``store.autorun`` — record the selector + initial-fire."""

        def decorator(func: Callable[[Any], None]) -> Callable[[Any], None]:
            current = selector(self._read_state)
            # Initial fire — mirrors redux autorun behaviour.
            func(current)
            self._autoruns.append((selector, func, [current]))
            return func

        return decorator

    def set_listening(self, *, value: bool) -> None:
        """Mutate the watched value and fire any autoruns that changed."""
        self._is_listening = value
        for selector, func, prev_box in self._autoruns:
            new = selector(self._read_state)
            if new != prev_box[0]:
                prev_box[0] = new
                func(new)


@pytest.fixture
def voice_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[
    tuple[Any, FakeStore, MagicMock, SimpleNamespace],
    None,
    None,
]:
    """Load the chat service's ubo_handle with a fake store + create_task.

    Returns ``(module, fake_store, create_task_mock, types)``. ``types``
    holds the store classes loaded *inside* the fixture — so they share
    class identity with what the voice handler's lazy imports see.
    """
    service_path = (
        Path(__file__).resolve().parents[2]
        / 'ubo_app'
        / 'services'
        / '090-chat'
        / 'ubo_handle.py'
    )

    fake_store = FakeStore()
    create_task_mock = MagicMock(return_value=MagicMock(name='AsyncHandle'))

    # Stub the modules the handler's lazy imports resolve. Crucially we
    # **never load** the real ``ubo_app.store.main`` — that import spins
    # up the global redux store + scheduler thread, whose long-lived
    # state then drifts subsequent flow tests' deterministic
    # ``ChatMessage`` IDs.
    import types

    fake_store_main = types.ModuleType('ubo_app.store.main')
    fake_store_main.store = fake_store  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'ubo_app.store.main', fake_store_main)

    fake_async = types.ModuleType('ubo_app.utils.async_')
    fake_async.create_task = create_task_mock  # type: ignore[attr-defined]
    fake_async.to_thread = MagicMock(name='to_thread')  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'ubo_app.utils.async_', fake_async)

    spec = importlib.util.spec_from_file_location(
        '_test_chat_ubo_handle',
        service_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.__dict__['register'] = lambda **_kwargs: None
    sys.modules[spec.name] = module
    modules_before = set(sys.modules)
    try:
        spec.loader.exec_module(module)

        # Reset module-level handler state between tests so leakage from
        # one scenario can't pollute the next.
        module._voice_state.is_listening = False  # noqa: SLF001
        module._voice_state.user_message_id = ''  # noqa: SLF001
        module._voice_state.assistant_message_id = ''  # noqa: SLF001
        module._voice_state.awaiting_response = False  # noqa: SLF001
        module._voice_state.turn_ended_at = 0.0  # noqa: SLF001
        module._voice_state.dismiss_handle = None  # noqa: SLF001
        module._voice_state.timer_initiated_dismiss = False  # noqa: SLF001

        voice_subscriptions = module._register_voice_handler()  # noqa: SLF001
        # Stash the cleanup list on the module for tests that exercise teardown.
        module._test_voice_subscriptions = voice_subscriptions  # type: ignore[attr-defined]  # noqa: SLF001

        # Capture the store classes the handler's lazy imports actually
        # used so tests' ``isinstance`` checks share class identity with
        # the dispatched actions/events.
        from ubo_app.store.services import (
            assistant as _assistant_mod,
        )
        from ubo_app.store.services import chat as _chat_mod

        captured_types = SimpleNamespace(
            LIVE_PIPELINE_SOURCE_ID=_assistant_mod.LIVE_PIPELINE_SOURCE_ID,
            REQUEST_PIPELINE_SOURCE_ID=_assistant_mod.REQUEST_PIPELINE_SOURCE_ID,
            AssistanceAudioFrame=_assistant_mod.AssistanceAudioFrame,
            AssistanceTextFrame=_assistant_mod.AssistanceTextFrame,
            AssistantHandleReportEvent=_assistant_mod.AssistantHandleReportEvent,
            AssistantPipelineStage=_assistant_mod.AssistantPipelineStage,
            AssistantStopListeningAction=_assistant_mod.AssistantStopListeningAction,
            AssistantStopTalkingAction=_assistant_mod.AssistantStopTalkingAction,
            ChatAddMessageAction=_chat_mod.ChatAddMessageAction,
            ChatAppendToMessageAction=_chat_mod.ChatAppendToMessageAction,
            ChatRole=_chat_mod.ChatRole,
            ChatSessionEndedEvent=_chat_mod.ChatSessionEndedEvent,
            ChatSetMessageTextAction=_chat_mod.ChatSetMessageTextAction,
            ChatStartSessionAction=_chat_mod.ChatStartSessionAction,
        )
        yield module, fake_store, create_task_mock, captured_types
    finally:
        # Drop every module my exec / lazy imports brought in — flow tests
        # later in the session re-import them against ``mock_environment``'s
        # patched ``uuid4`` and rely on getting fresh module objects.
        for module_name in set(sys.modules) - modules_before:
            sys.modules.pop(module_name, None)
        sys.modules.pop(spec.name, None)
        # Force-evict chat + assistant services even if they were already
        # in sys.modules before my fixture loaded — both modules bind
        # ``from uuid import uuid4`` at import time, and that binding
        # must be the *patched* uuid4 by the time ``mock_environment``-
        # guarded flow tests boot their own store.
        for module_name in (
            'ubo_app.store.services.chat',
            'ubo_app.store.services.assistant',
        ):
            sys.modules.pop(module_name, None)


_VoiceHandler = tuple[Any, 'FakeStore', MagicMock, SimpleNamespace]


def _make_text_frame(
    types: SimpleNamespace,
    *,
    text: str,
    source: Any,  # noqa: ANN401  # AssistantPipelineStage member
    is_last_frame: bool = False,
) -> Any:  # noqa: ANN401
    return types.AssistanceTextFrame(
        text=text,
        source=source,
        is_last_frame=is_last_frame,
        timestamp=0,
        id='f',
        index=0,
    )


def _make_audio_frame(types: SimpleNamespace) -> Any:  # noqa: ANN401
    return types.AssistanceAudioFrame(
        audio=None,
        is_last_frame=False,
        timestamp=0,
        id='a',
        index=0,
    )


def _report(
    types: SimpleNamespace,
    frame: Any,  # noqa: ANN401
    source_id: str | None = None,
) -> Any:  # noqa: ANN401
    if source_id is None:
        source_id = types.LIVE_PIPELINE_SOURCE_ID
    return types.AssistantHandleReportEvent(source_id=source_id, data=frame)


def test_listening_rising_edge_starts_chat_session(
    voice_handler: _VoiceHandler,
) -> None:
    """False→True on ``is_listening`` must dispatch ``ChatStartSessionAction``."""
    _module, fake_store, _, types = voice_handler
    fake_store.set_listening(value=True)
    assert any(
        isinstance(a, types.ChatStartSessionAction)
        for a in fake_store.dispatched
    )


def test_listening_falling_edge_arms_processing_hold(
    voice_handler: _VoiceHandler,
) -> None:
    """True→False on ``is_listening`` arms the post-turn processing hold.

    Non-streaming STT writes nothing during the turn, so the chat must be
    held open between the user releasing the key and the first response
    frame — ``_should_dismiss`` gates on this flag.
    """
    module, fake_store, _, _ = voice_handler
    fake_store.set_listening(value=True)
    assert module._voice_state.awaiting_response is False  # noqa: SLF001

    fake_store.set_listening(value=False)

    assert module._voice_state.awaiting_response is True  # noqa: SLF001
    assert module._voice_state.turn_ended_at > 0  # noqa: SLF001


def test_report_frame_does_not_eagerly_clear_hold(
    voice_handler: _VoiceHandler,
) -> None:
    """The report handler must NOT eagerly clear the processing hold.

    Regression guard: ``store.dispatch`` only queues the ``last_activity_time``
    bump (applied later on the scheduler thread). If the handler cleared the
    hold flag here, the dismiss loop (a different thread) could observe the
    cleared flag together with the still-stale session-start
    ``last_activity_time`` and race a spurious dismiss. The hold is released
    instead by ``_should_dismiss`` observing the timestamp advance.
    """
    module, fake_store, _, types = voice_handler
    fake_store.set_listening(value=True)
    fake_store.set_listening(value=False)
    assert module._voice_state.awaiting_response is True  # noqa: SLF001

    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text='hello',
                source=types.AssistantPipelineStage.STT,
            ),
        ),
    )

    assert module._voice_state.awaiting_response is True  # noqa: SLF001


def test_rising_edge_clears_stale_processing_hold(
    voice_handler: _VoiceHandler,
) -> None:
    """Starting a new turn clears any leftover processing hold."""
    module, fake_store, _, _ = voice_handler
    fake_store.set_listening(value=True)
    fake_store.set_listening(value=False)
    assert module._voice_state.awaiting_response is True  # noqa: SLF001

    fake_store.set_listening(value=True)

    assert module._voice_state.awaiting_response is False  # noqa: SLF001


def _fake_chat(
    *,
    last_activity_time: float | None,
    is_active: bool = True,
    is_audio_playing: bool = False,
) -> SimpleNamespace:
    """Minimal stand-in for ``ChatState`` for ``_should_dismiss`` tests."""
    return SimpleNamespace(
        is_active=is_active,
        last_activity_time=last_activity_time,
        is_audio_playing=is_audio_playing,
    )


def test_should_dismiss_holds_while_post_turn_write_pending(
    voice_handler: _VoiceHandler,
) -> None:
    """The core race fix: a stale ``last_activity_time`` must NOT dismiss.

    After a long non-streaming turn ``last_activity_time`` is still the
    session-start value (far older than the idle delay), and the queued
    post-turn bubble bump hasn't landed yet (``last_activity_time <=
    turn_ended_at``). ``_should_dismiss`` must hold the chat open rather
    than racing the bump.
    """
    module, _, _, _ = voice_handler
    now = module.default_now()
    module._voice_state.awaiting_response = True  # noqa: SLF001
    module._voice_state.turn_ended_at = now  # noqa: SLF001
    # Session started 10 s ago; nothing written since — far past the 4 s
    # idle delay, yet <= turn_ended_at, so the hold must win.
    chat = _fake_chat(last_activity_time=now - 10)

    assert module._should_dismiss(chat) is False  # noqa: SLF001


def test_should_dismiss_releases_once_activity_advances(
    voice_handler: _VoiceHandler,
) -> None:
    """Once the post-turn write lands the hold releases to normal idle.

    A fresh ``last_activity_time`` (> ``turn_ended_at``) means the bump has
    been applied; within the idle delay the chat stays open under the
    normal rule, not the hold.
    """
    module, _, _, _ = voice_handler
    now = module.default_now()
    module._voice_state.awaiting_response = True  # noqa: SLF001
    module._voice_state.turn_ended_at = now - 10  # noqa: SLF001
    # STT bump landed 1 s ago — fresh (> turn_ended_at), within the 4 s
    # idle delay, so the chat stays open under the normal idle rule.
    chat = _fake_chat(last_activity_time=now - 1)

    assert module._should_dismiss(chat) is False  # noqa: SLF001

    # ...and once that (post-turn) activity itself goes idle, it dismisses.
    stale = _fake_chat(last_activity_time=now - 5)
    assert module._should_dismiss(stale) is True  # noqa: SLF001


def test_should_dismiss_hold_times_out_on_silent_turn(
    voice_handler: _VoiceHandler,
) -> None:
    """A turn that yields no output can't wedge the chat open forever."""
    module, _, _, _ = voice_handler
    now = module.default_now()
    timeout = module._AWAITING_RESPONSE_TIMEOUT_SECONDS  # noqa: SLF001
    module._voice_state.awaiting_response = True  # noqa: SLF001
    module._voice_state.turn_ended_at = now - (timeout + 1)  # noqa: SLF001
    # No post-turn write ever landed (still <= turn_ended_at) and the grace
    # window has elapsed — fall through to idle dismissal.
    chat = _fake_chat(last_activity_time=now - (timeout + 5))

    assert module._should_dismiss(chat) is True  # noqa: SLF001


def test_should_dismiss_respects_listening_and_audio_gates(
    voice_handler: _VoiceHandler,
) -> None:
    """Listening / active TTS playback keep the chat open regardless of idle."""
    module, _, _, _ = voice_handler
    now = module.default_now()
    stale = _fake_chat(last_activity_time=now - 10)

    module._voice_state.awaiting_response = False  # noqa: SLF001
    module._voice_state.is_listening = True  # noqa: SLF001
    assert module._should_dismiss(stale) is False  # noqa: SLF001

    module._voice_state.is_listening = False  # noqa: SLF001
    playing = _fake_chat(last_activity_time=now - 10, is_audio_playing=True)
    assert module._should_dismiss(playing) is False  # noqa: SLF001

    # Plain idle, no gates → dismiss.
    assert module._should_dismiss(stale) is True  # noqa: SLF001


def test_stt_first_frame_creates_user_bubble(
    voice_handler: _VoiceHandler,
) -> None:
    """The first STT frame must create a USER bubble with the partial text."""
    module, fake_store, _, types = voice_handler
    fake_store.set_listening(value=True)
    fake_store.dispatched.clear()

    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text='hello',
                source=types.AssistantPipelineStage.STT,
            ),
        ),
    )

    add = next(
        a
        for a in fake_store.dispatched
        if isinstance(a, types.ChatAddMessageAction)
    )
    assert add.message.role == types.ChatRole.USER
    assert add.message.text == 'hello'
    assert module._voice_state.user_message_id == add.message.id  # noqa: SLF001


def test_stt_subsequent_frame_overwrites_text(
    voice_handler: _VoiceHandler,
) -> None:
    """STT interim frames are cumulative — overwrite, never append."""
    module, fake_store, _, types = voice_handler
    fake_store.set_listening(value=True)

    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text='hel',
                source=types.AssistantPipelineStage.STT,
            ),
        ),
    )
    msg_id = module._voice_state.user_message_id  # noqa: SLF001
    fake_store.dispatched.clear()

    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text='hello world',
                source=types.AssistantPipelineStage.STT,
            ),
        ),
    )
    set_action = next(
        a
        for a in fake_store.dispatched
        if isinstance(a, types.ChatSetMessageTextAction)
    )
    assert set_action.message_id == msg_id
    assert set_action.text == 'hello world'


def test_stt_final_frame_clears_user_id(voice_handler: _VoiceHandler) -> None:
    """``is_last_frame`` on the STT stream closes the USER bubble."""
    module, fake_store, _, types = voice_handler
    fake_store.set_listening(value=True)
    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text='hi',
                source=types.AssistantPipelineStage.STT,
            ),
        ),
    )
    assert module._voice_state.user_message_id  # noqa: SLF001

    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text='hi there',
                source=types.AssistantPipelineStage.STT,
                is_last_frame=True,
            ),
        ),
    )
    assert module._voice_state.user_message_id == ''  # noqa: SLF001


def test_llm_first_frame_creates_assistant_bubble(
    voice_handler: _VoiceHandler,
) -> None:
    """The first LLM delta must create an ASSISTANT bubble with that chunk."""
    module, fake_store, _, types = voice_handler
    fake_store.set_listening(value=True)
    fake_store.dispatched.clear()

    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text='Hi',
                source=types.AssistantPipelineStage.LLM,
            ),
        ),
    )

    add = next(
        a
        for a in fake_store.dispatched
        if isinstance(a, types.ChatAddMessageAction)
    )
    assert add.message.role == types.ChatRole.ASSISTANT
    assert add.message.text == 'Hi'
    assert module._voice_state.assistant_message_id == add.message.id  # noqa: SLF001


def test_llm_subsequent_frame_appends_chunk(
    voice_handler: _VoiceHandler,
) -> None:
    """LLM frames are deltas — append, never overwrite."""
    module, fake_store, _, types = voice_handler
    fake_store.set_listening(value=True)

    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text='Hi',
                source=types.AssistantPipelineStage.LLM,
            ),
        ),
    )
    msg_id = module._voice_state.assistant_message_id  # noqa: SLF001
    fake_store.dispatched.clear()

    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text=' there',
                source=types.AssistantPipelineStage.LLM,
            ),
        ),
    )
    append = next(
        a
        for a in fake_store.dispatched
        if isinstance(a, types.ChatAppendToMessageAction)
    )
    assert append.message_id == msg_id
    assert append.chunk == ' there'


def test_non_pipecat_source_id_is_ignored(
    voice_handler: _VoiceHandler,
) -> None:
    """One-shot programmatic requests must not drive the chat overlay."""
    _module, fake_store, _, types = voice_handler
    fake_store.set_listening(value=True)
    fake_store.dispatched.clear()

    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text='hello',
                source=types.AssistantPipelineStage.STT,
            ),
            source_id=types.REQUEST_PIPELINE_SOURCE_ID,
        ),
    )
    assert not any(
        isinstance(a, types.ChatAddMessageAction)
        for a in fake_store.dispatched
    )


def test_audio_frames_do_not_route_to_bubbles(
    voice_handler: _VoiceHandler,
) -> None:
    """Audio frames must be ignored by the report handler.

    The chat reducer observes ``AudioPlayAudioSequenceAction`` directly to
    stamp ``last_activity_time``; the voice handler only routes *text*
    frames into bubbles.
    """
    _module, fake_store, _, types = voice_handler
    fake_store.set_listening(value=True)
    fake_store.dispatched.clear()

    fake_store.fire_event(_report(types, _make_audio_frame(types)))

    assert not any(
        isinstance(a, types.ChatAddMessageAction)
        for a in fake_store.dispatched
    )


def test_external_session_ended_stops_assistant(
    voice_handler: _VoiceHandler,
) -> None:
    """An *external* ``ChatSessionEndedEvent`` (Back, etc.) stops the assistant.

    The ``timer_initiated_dismiss`` flag is False by default — only our
    own dismiss loop sets it.
    """
    module, fake_store, _, types = voice_handler
    fake_store.dispatched.clear()
    assert module._voice_state.timer_initiated_dismiss is False  # noqa: SLF001

    fake_store.fire_event(types.ChatSessionEndedEvent(session_id='s1'))

    assert any(
        isinstance(a, types.AssistantStopListeningAction)
        for a in fake_store.dispatched
    )
    assert any(
        isinstance(a, types.AssistantStopTalkingAction)
        for a in fake_store.dispatched
    )


def test_timer_initiated_session_ended_does_not_stop_assistant(
    voice_handler: _VoiceHandler,
) -> None:
    """Auto-dismiss-timer path must NOT dispatch ``AssistantStop*``."""
    module, fake_store, _, types = voice_handler
    fake_store.dispatched.clear()
    module._voice_state.timer_initiated_dismiss = True  # noqa: SLF001

    fake_store.fire_event(types.ChatSessionEndedEvent(session_id='s1'))

    assert not any(
        isinstance(a, types.AssistantStopListeningAction)
        for a in fake_store.dispatched
    )
    assert not any(
        isinstance(a, types.AssistantStopTalkingAction)
        for a in fake_store.dispatched
    )
    assert module._voice_state.timer_initiated_dismiss is False  # noqa: SLF001


def test_dismiss_loop_started_on_register(
    voice_handler: _VoiceHandler,
) -> None:
    """The fixture invocation registers the handler — confirm the loop is up."""
    module, _, create_task_mock, _ = voice_handler
    assert create_task_mock.call_count >= 1
    assert module._voice_state.dismiss_handle is not None  # noqa: SLF001


def test_register_voice_handler_returns_cleanup_subscriptions(
    voice_handler: _VoiceHandler,
) -> None:
    """``_register_voice_handler`` must hand back cleanup callables.

    Without these the service can't be torn down (hot-reload / tests) and
    subscriptions leak — duplicating handlers across reload generations.
    """
    module, fake_store, _, types = voice_handler
    subscriptions = module._test_voice_subscriptions  # noqa: SLF001
    # autorun unsub + 2 event-subscriber unsubs + dismiss-task cancel.
    expected_subscription_count = 4
    assert len(list(subscriptions)) == expected_subscription_count

    # Running every cleanup must cancel the dismiss task and detach the
    # report subscriber so post-cleanup events don't reach the handler.
    for cleanup in subscriptions:
        cleanup()
    assert module._voice_state.dismiss_handle is None  # noqa: SLF001
    fake_store.dispatched.clear()
    fake_store.fire_event(
        _report(
            types,
            _make_text_frame(
                types,
                text='post-teardown',
                source=types.AssistantPipelineStage.STT,
            ),
        ),
    )
    # No subscriber should still be wired — no ChatAddMessageAction.
    assert not any(
        isinstance(a, types.ChatAddMessageAction)
        for a in fake_store.dispatched
    )

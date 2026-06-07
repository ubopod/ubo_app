"""Chat widget window-snapshot test harness.

Boots a minimal app (the ``chat`` + ``keypad`` services only) **once** and
drives every chat-widget scenario through it — a full conversation, text
streaming, the echo round-trip, and long-message scrolling — capturing
window + store snapshots at every milestone. Booting is expensive (~45s
plus the first-capture cost), so all scenarios share a single session;
each begins with ``ChatStartSessionAction``, which fully resets the chat
state, keeping them independent. Snapshot titles are prefixed per scenario.

Phase 1: run locally with ``--override-window-snapshots --make-screenshots
--override-store-snapshots`` to produce reviewable PNG screenshots under
``tests/flows/results/test_chat_widget/`` and check them against the mock-up.
Then run in Docker to generate the ``rpi`` hash baselines.

Button input (L3 to toggle audio, UP/DOWN to scroll) goes through *real
gRPC keypad presses* via the ``dispatcher`` fixture — never a direct
``store.dispatch`` — so the test exercises the same path as the hardware.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import (
        AppContext,
        Dispatcher,
        LoadServices,
        Stability,
    )
    from tests.fixtures.load_services import AsyncUnloadWaiter
    from tests.fixtures.snapshot import WindowSnapshot
    from ubo_app.store.main import RootState

# Kept short so the ``conversation-04`` snapshot shows two clean bubbles with
# no partial text from this earlier reply clipping into the top of the frame.
_ASSISTANT_TEXT = 'dolore magna aliqua. ut enim ad minim veniam, quis nostrud.'
_USER_TEXT = 'what is the population of latin american countries combined?'

# A reply far taller than the 240px screen, to exercise scrolling.
_LONG_TEXT = (
    'Latin America spans from Mexico down to the southern tip of '
    'Argentina and Chile, covering twenty sovereign countries plus '
    'several territories. The region is home to roughly six hundred and '
    'sixty million people who speak mostly Spanish and Portuguese, '
    'alongside hundreds of indigenous languages still in daily use. Its '
    'geography ranges from the Amazon rainforest and the Andes mountains '
    'to vast grasslands, high deserts, and long coastlines on both the '
    'Atlantic and Pacific oceans. The economies, cultures, and climates '
    'vary enormously from one country to the next.'
)


def _normalize_chat(state: RootState) -> dict[str, Any]:
    """Select chat state with volatile fields dropped for snapshots."""
    from ubo_app.store.core.types import ChatViewData

    chat_state = state.chat
    messages = [
        {
            'id': message.id,
            'role': message.role.value,
            'kind': message.kind.value,
            'text': message.text,
            'audio_id': message.audio_id,
            'is_playing': message.is_playing,
        }
        for message in chat_state.messages
    ]
    current_view = state.main.current_view
    bubbles: list[dict[str, Any]] = []
    scroll_offset: int | None = None
    if isinstance(current_view, ChatViewData):
        scroll_offset = current_view.scroll_offset
        bubbles = [
            {
                'role': bubble.role,
                'alignment': bubble.alignment,
                'kind': bubble.kind,
                'pointer_key': bubble.pointer_key,
                'is_playing': bubble.is_playing,
            }
            for bubble in current_view.bubbles
        ]
    return {
        'messages': messages,
        'session_id': chat_state.session_id,
        'is_active': chat_state.is_active,
        'current_view_type': type(current_view).__name__,
        'bubbles': bubbles,
        'scroll_offset': scroll_offset,
        'stack': [type(item).__name__ for item in state.main.stack],
    }


async def _boot_minimal_app(
    app_context: AppContext,
    load_services: LoadServices,
    wait_for: WaitFor,
) -> AsyncUnloadWaiter:
    """Boot the app with the chat + keypad services; wait until ready."""
    from tenacity import wait_fixed

    from ubo_app.store.main import store

    app_context.set_app()
    unload_waiter = await load_services(['chat', 'keypad'], run_async=True)

    @wait_for(run_async=True, wait=wait_fixed(1))
    def stack_is_loaded() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        assert len(state.main.stack) > 0

    await stack_is_loaded()
    return unload_waiter


@pytest.mark.timeout(400)
async def test_chat_widget_flows(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    dispatcher: Dispatcher,
) -> None:
    """Every chat-widget scenario, driven through one shared app boot.

    Scenarios run back to back — a full conversation, character streaming,
    the echo round-trip, and long-message scrolling. Each starts with
    ``ChatStartSessionAction`` (a full chat reset), so they stay
    independent despite sharing the session. Window + store snapshots are
    captured at each milestone with a per-scenario title prefix.
    """
    from ubo_app.store.main import store
    from ubo_app.store.services.chat import (
        ChatAddMessageAction,
        ChatAppendToMessageAction,
        ChatEndSessionAction,
        ChatMessage,
        ChatMessageKind,
        ChatRole,
        ChatSendUserMessageAction,
        ChatStartSessionAction,
    )
    from ubo_app.store.services.keypad import Key

    unload_waiter = await _boot_minimal_app(app_context, load_services, wait_for)

    def snap(title: str) -> None:
        window_snapshot.take(title=title)
        store_snapshot.take(selector=_normalize_chat)

    # ================================================================
    # Scenario 1 — a full conversation: text bubbles, audio, scroll.
    # ================================================================
    store.dispatch(ChatStartSessionAction(session_id='chat-conversation'))
    await stability(initial_wait=4)
    snap('conversation-01-empty')

    store.dispatch(
        ChatAddMessageAction(
            message=ChatMessage(
                id='msg-1',
                role=ChatRole.ASSISTANT,
                kind=ChatMessageKind.TEXT,
                text=_ASSISTANT_TEXT,
                timestamp=0,
            ),
        ),
    )
    await stability(initial_wait=2)
    snap('conversation-02-assistant-text')

    store.dispatch(
        ChatAddMessageAction(
            message=ChatMessage(
                id='msg-2',
                role=ChatRole.USER,
                kind=ChatMessageKind.TEXT,
                text=_USER_TEXT,
                timestamp=0,
            ),
        ),
    )
    await stability(initial_wait=2)
    snap('conversation-03-user-text')

    store.dispatch(
        ChatAddMessageAction(
            message=ChatMessage(
                id='msg-3',
                role=ChatRole.ASSISTANT,
                kind=ChatMessageKind.TEXT,
                text='Around 660 million people live in Latin America.',
                timestamp=0,
            ),
        ),
    )
    await stability(initial_wait=2)
    snap('conversation-04-assistant-reply')

    store.dispatch(
        ChatAddMessageAction(
            message=ChatMessage(
                id='msg-4',
                role=ChatRole.USER,
                kind=ChatMessageKind.AUDIO,
                audio_id='clip-a',
                timestamp=0,
            ),
        ),
    )
    await stability(initial_wait=2)
    snap('conversation-05-audio-bubble')

    # Press L3 → the audio bubble starts "playing".
    await dispatcher.send_key(Key.L3)
    await stability(initial_wait=2)
    snap('conversation-06-audio-playing')

    # Press UP → scroll back into history.
    await dispatcher.send_key(Key.UP)
    await stability(initial_wait=2)
    snap('conversation-07-scrolled')

    # End the session → the overlay closes.
    store.dispatch(ChatEndSessionAction())
    await stability(initial_wait=2)
    snap('conversation-08-closed')

    # ================================================================
    # Scenario 2 — stream an assistant reply character by character.
    # ================================================================
    store.dispatch(ChatStartSessionAction(session_id='chat-stream'))
    store.dispatch(
        ChatAddMessageAction(
            message=ChatMessage(
                id='msg-q',
                role=ChatRole.USER,
                kind=ChatMessageKind.TEXT,
                text='tell me about latin america',
                timestamp=0,
            ),
        ),
    )
    store.dispatch(
        ChatAddMessageAction(
            message=ChatMessage(
                id='msg-stream',
                role=ChatRole.ASSISTANT,
                kind=ChatMessageKind.TEXT,
                text='',
                timestamp=0,
            ),
        ),
    )
    await stability(initial_wait=2)
    snap('streaming-01-empty-reply')

    reply = (
        'Latin America is home to roughly 660 million people '
        'across 20 countries.'
    )
    checkpoints = {24: 'streaming-02-streaming-early', 56: 'streaming-03-mid'}
    for index, character in enumerate(reply, start=1):
        store.dispatch(
            ChatAppendToMessageAction(message_id='msg-stream', chunk=character),
        )
        await asyncio.sleep(0.05)
        if index in checkpoints:
            await stability(initial_wait=1)
            snap(checkpoints[index])

    await stability(initial_wait=2)
    snap('streaming-04-complete')

    # ================================================================
    # Scenario 3 — a sent user message is echoed back by the service.
    # ================================================================
    store.dispatch(ChatStartSessionAction(session_id='chat-echo'))
    await stability(initial_wait=2)
    snap('echo-01-opened')

    store.dispatch(
        ChatSendUserMessageAction(text='hello there', message_id='echo-user'),
    )
    await stability(initial_wait=2)
    snap('echo-02-echoed')

    state = store._state  # noqa: SLF001
    assert state is not None
    conversation = [
        (message.role.value, message.text)
        for message in state.chat.messages
    ]
    assert conversation == [
        ('user', 'hello there'),
        ('assistant', 'echo=> hello there'),
    ]

    # ================================================================
    # Scenario 4 — a message taller than the screen scrolls fully.
    # ================================================================
    store.dispatch(ChatStartSessionAction(session_id='chat-scroll'))
    store.dispatch(
        ChatAddMessageAction(
            message=ChatMessage(
                id='long',
                role=ChatRole.ASSISTANT,
                kind=ChatMessageKind.TEXT,
                text=_LONG_TEXT,
                timestamp=0,
            ),
        ),
    )
    # Bottom-anchored by default — the end of the message is visible.
    await stability(initial_wait=2)
    snap('scroll-01-bottom')
    hash_bottom = window_snapshot.hash

    # Press UP — pan toward the start of the message.
    await dispatcher.send_key(Key.UP)
    await stability(initial_wait=2)
    snap('scroll-02-scrolled-up')
    hash_up = window_snapshot.hash
    assert hash_up != hash_bottom, 'pressing UP must scroll the long message'

    # Keep scrolling up toward the very start.
    for _ in range(5):
        await dispatcher.send_key(Key.UP)
    await stability(initial_wait=2)
    snap('scroll-03-near-top')
    assert window_snapshot.hash != hash_up, 'further UP presses must keep scrolling'

    # Scroll all the way back down — returns to the end.
    for _ in range(10):
        await dispatcher.send_key(Key.DOWN)
    await stability(initial_wait=2)
    snap('scroll-04-back-at-bottom')
    assert window_snapshot.hash == hash_bottom, (
        'scrolling back down must return to the end of the message'
    )

    await unload_waiter()

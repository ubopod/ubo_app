"""Chat widget window-snapshot test harness.

Boots a minimal app (the ``chat`` + ``keypad`` services only) and drives a
deterministic conversation through the Redux store — mock assistant/user
text bubbles and an audio bubble — capturing window + store snapshots at
every milestone.

Phase 1: run locally with ``--override-window-snapshots --make-screenshots
--override-store-snapshots`` to produce reviewable PNG screenshots under
``tests/flows/results/test_chat_widget/`` and check them against the mock-up.
Then run in Docker to generate the ``rpi`` hash baselines.

Button input (L3 to toggle audio, UP to scroll) goes through *real gRPC
keypad presses* via the ``dispatcher`` fixture — never a direct
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

_ASSISTANT_TEXT = (
    'dolore magna aliqua. ut enim ad minim veniam, quis nostrud '
    'exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.'
)
_USER_TEXT = 'what is the population of latin american countries combined?'


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


@pytest.mark.timeout(200)
async def test_chat_conversation_flow(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    dispatcher: Dispatcher,
) -> None:
    """Drive a full chat session: text bubbles, an audio bubble, scroll.

    Captures a window + store snapshot at each milestone. Pressing L3
    toggles the audio bubble; pressing UP scrolls back into history — both
    via real gRPC keypad presses.
    """
    from ubo_app.store.main import store
    from ubo_app.store.services.chat import (
        ChatAddMessageAction,
        ChatEndSessionAction,
        ChatMessage,
        ChatMessageKind,
        ChatRole,
        ChatStartSessionAction,
    )
    from ubo_app.store.services.keypad import Key

    unload_waiter = await _boot_minimal_app(app_context, load_services, wait_for)

    def snap(title: str) -> None:
        window_snapshot.take(title=title)
        store_snapshot.take(selector=_normalize_chat)

    # --- Stage 1: open an empty chat overlay -----------------------------
    store.dispatch(ChatStartSessionAction(session_id='chat-test'))
    await stability(initial_wait=4)
    snap('01-empty')

    # --- Stage 2: assistant text bubble ----------------------------------
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
    snap('02-assistant-text')

    # --- Stage 3: user text bubble ---------------------------------------
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
    snap('03-user-text')

    # --- Stage 4: assistant reply ----------------------------------------
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
    snap('04-assistant-reply')

    # --- Stage 5: user audio bubble (bound to L3) ------------------------
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
    snap('05-audio-bubble')

    # --- Stage 6: press L3 → audio bubble starts "playing" ---------------
    await dispatcher.send_key(Key.L3)
    await stability(initial_wait=2)
    snap('06-audio-playing')

    # --- Stage 7: press UP → scroll back into history --------------------
    await dispatcher.send_key(Key.UP)
    await stability(initial_wait=2)
    snap('07-scrolled')

    # --- Stage 8: end the session → overlay closes -----------------------
    store.dispatch(ChatEndSessionAction())
    await stability(initial_wait=2)
    snap('08-closed')

    await unload_waiter()


@pytest.mark.timeout(200)
async def test_chat_text_streaming(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
) -> None:
    """Stream an assistant reply into a bubble one character at a time.

    Proves the chat widget renders streamed text: an empty assistant bubble
    is created, then ``ChatAppendToMessageAction`` chunks arrive character
    by character. The bubble wraps and grows to fit as the text lengthens.
    """
    from ubo_app.store.main import store
    from ubo_app.store.services.chat import (
        ChatAddMessageAction,
        ChatAppendToMessageAction,
        ChatMessage,
        ChatMessageKind,
        ChatRole,
        ChatStartSessionAction,
    )

    unload_waiter = await _boot_minimal_app(app_context, load_services, wait_for)

    def snap(title: str) -> None:
        window_snapshot.take(title=title)
        store_snapshot.take(selector=_normalize_chat)

    # --- A user question, then an empty assistant bubble to stream into --
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
    await stability(initial_wait=4)
    snap('01-empty-reply')

    # --- Stream the reply character by character -------------------------
    reply = (
        'Latin America is home to roughly 660 million people '
        'across 20 countries.'
    )
    checkpoints = {24: '02-streaming-early', 56: '03-streaming-mid'}
    for index, character in enumerate(reply, start=1):
        store.dispatch(
            ChatAppendToMessageAction(message_id='msg-stream', chunk=character),
        )
        await asyncio.sleep(0.05)
        if index in checkpoints:
            await stability(initial_wait=1)
            snap(checkpoints[index])

    await stability(initial_wait=2)
    snap('04-streaming-complete')

    await unload_waiter()

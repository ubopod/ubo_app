# ruff: noqa: D100, D103
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import ReducerRegistrar, register

    from ubo_app.store.services.chat import ChatUserMessageSentEvent


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


def setup(register_reducer: ReducerRegistrar) -> None:
    from reducer import reducer

    from ubo_app.utils import IS_TEST_ENV

    register_reducer(reducer)
    _register_chat_menu_item()
    # The echo responder is dev/test scaffolding — register it only under
    # the test harness so it never collides with the real assistant
    # responder (phase 2) in normal operation.
    if IS_TEST_ENV:
        _register_echo_handler()


register(
    service_id='chat',
    label='Chat',
    setup=setup,
)

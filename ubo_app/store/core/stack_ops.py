"""Stack manipulation functions for Redux state management.

This module provides pure functions for manipulating the navigation stack.
These functions are used by the reducer to handle stack-related actions.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    ApplicationStackItem,
    InstructionStackItem,
    MenuStackItem,
    NotificationStackItem,
    PromptStackItem,
    RenderStackItem,
)

if TYPE_CHECKING:
    from ubo_app.store.core.types import MainState, MenuItemData, StackItemType
    from ubo_app.store.ubo_actions import BasicType


def derive_path_from_stack(stack: tuple[StackItemType, ...]) -> tuple[str, ...]:
    """Derive the menu path from the stack.

    Returns a tuple of menu keys representing the navigation path.
    Only MenuStackItems contribute to the path (apps and notifications don't).
    The first item (root) is excluded from the path.
    """
    return tuple(
        item.menu_key for item in stack if isinstance(item, MenuStackItem)
    )[1:]


def create_root_stack_item() -> tuple[MenuStackItem]:
    """Create the initial root stack item for the home menu."""
    return (
        MenuStackItem(
            id=uuid.uuid4().hex,
            menu_key='',  # Root has empty key
            page_index=0,
        ),
    )


def push_menu(state: MainState, menu_key: str) -> MainState:
    """Push a menu onto the navigation stack.

    Args:
        state: Current main state.
        menu_key: Key of the SubMenuItem that was selected.

    Returns:
        New state with the menu pushed onto the stack, or the same state
        unchanged if the top of stack already has the same menu_key.

    """
    # Prevent duplicate consecutive pushes of the same menu
    if (
        state.stack
        and isinstance(state.stack[-1], MenuStackItem)
        and state.stack[-1].menu_key == menu_key
    ):
        return state

    new_item = MenuStackItem(
        id=uuid.uuid4().hex,
        menu_key=menu_key,
        page_index=0,
    )
    new_stack = (*state.stack, new_item)
    new_path = derive_path_from_stack(new_stack)
    return replace(state, stack=new_stack, path=new_path)


def push_application(
    state: MainState,
    application_id: str,
    initialization_args: tuple[BasicType, ...] = (),
    initialization_kwargs: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] | None = None,
) -> MainState:
    """Push an application onto the navigation stack.

    Args:
        state: Current main state.
        application_id: Registered application ID.
        initialization_args: Arguments passed when opening the application.
        initialization_kwargs: Keyword arguments passed when opening.

    Returns:
        New state with the application pushed onto the stack.

    """
    if initialization_kwargs is None:
        initialization_kwargs = {}
    new_item = ApplicationStackItem(
        id=uuid.uuid4().hex,
        application_id=application_id,
        initialization_args=initialization_args,
        initialization_kwargs=initialization_kwargs,
    )
    new_stack = (*state.stack, new_item)
    # Path unchanged - applications don't contribute to path
    return replace(state, stack=new_stack)


def push_render(  # noqa: PLR0913
    state: MainState,
    kind: str,
    *,
    title: str = '',
    props: dict[
        str,
        BasicType | tuple[BasicType, ...] | list[BasicType],
    ] | None = None,
    items: tuple[MenuItemData, ...] = (),
    stream_id: str = '',
) -> MainState:
    """Push a generic reusable render view onto the navigation stack."""
    if props is None:
        props = {}
    new_item = RenderStackItem(
        id=uuid.uuid4().hex,
        kind=kind,
        title=title,
        props=props,
        items=items,
        stream_id=stream_id,
    )
    new_stack = (*state.stack, new_item)
    return replace(state, stack=new_stack)


def push_notification(state: MainState, notification_id: str) -> MainState:
    """Push a notification overlay onto the navigation stack.

    Idempotent: if a ``NotificationStackItem`` with the same
    ``notification_id`` is already on the stack, the state is returned
    unchanged. This lets callers fire ``StackPushNotificationAction``
    freely (e.g. on every progress update) without reading the stack
    first — the reducer dedups against current state, avoiding the
    stale-read races that arise when many notification actions batch.

    Args:
        state: Current main state.
        notification_id: ID of the notification to display.

    Returns:
        New state with the notification pushed onto the stack, or the
        unchanged state if it is already present.

    """
    if any(
        isinstance(item, NotificationStackItem)
        and item.notification_id == notification_id
        for item in state.stack
    ):
        return state
    new_item = NotificationStackItem(
        id=uuid.uuid4().hex,
        notification_id=notification_id,
    )
    new_stack = (*state.stack, new_item)
    # Path unchanged - notifications don't contribute to path
    return replace(state, stack=new_stack)


def pop_notification(state: MainState, notification_id: str) -> MainState:
    """Remove a notification overlay from the navigation stack by id.

    Removes the ``NotificationStackItem`` whose ``notification_id``
    matches. No-op when it isn't on the stack. Evaluated entirely
    against the passed-in state, so it is safe to dispatch even when
    other stack mutations are still queued.

    Args:
        state: Current main state.
        notification_id: ID of the notification to remove.

    Returns:
        New state with the notification removed, or the unchanged state
        if it was not present.

    """
    new_stack = tuple(
        item
        for item in state.stack
        if not (
            isinstance(item, NotificationStackItem)
            and item.notification_id == notification_id
        )
    )
    if new_stack == state.stack:
        return state
    # Path unchanged - notifications don't contribute to path
    return replace(state, stack=new_stack)


def push_instruction(  # noqa: PLR0913
    state: MainState,
    *,
    title: str = '',
    instruction: str = '',
    icon: str = '',
    spinner: bool = False,
    timeout_seconds: int = 0,
    footer_text: str = '',
) -> MainState:
    """Push an instruction/waiting view onto the navigation stack."""
    new_item = InstructionStackItem(
        id=uuid.uuid4().hex,
        title=title,
        instruction=instruction,
        icon=icon,
        spinner=spinner,
        timeout_seconds=timeout_seconds,
        footer_text=footer_text,
    )
    new_stack = (*state.stack, new_item)
    # Path unchanged - instructions don't contribute to path
    return replace(state, stack=new_stack)


def push_prompt(
    state: MainState,
    *,
    title: str = '',
    prompt: str = '',
    icon: str = '',
    items: tuple[MenuItemData, ...] = (),
) -> MainState:
    """Push a prompt/confirmation view onto the navigation stack."""
    new_item = PromptStackItem(
        id=uuid.uuid4().hex,
        title=title,
        prompt=prompt,
        icon=icon,
        items=items,
    )
    new_stack = (*state.stack, new_item)
    # Path unchanged - prompts don't contribute to path
    return replace(state, stack=new_stack)


def pop_stack(state: MainState, count: int = 1) -> MainState | None:
    """Pop items from the navigation stack.

    Args:
        state: Current main state.
        count: Number of items to pop.

    Returns:
        New state with items popped, or None if can't pop (at root).

    """
    if len(state.stack) <= 1:
        return None  # Can't pop root
    # Pop 'count' items but always keep at least root
    pop_count = min(count, len(state.stack) - 1)
    new_stack = state.stack[:-pop_count] if pop_count > 0 else state.stack
    new_path = derive_path_from_stack(new_stack)
    return replace(state, stack=new_stack, path=new_path)


def pop_to_root(state: MainState) -> MainState | None:
    """Pop all items except root, returning to home screen.

    Args:
        state: Current main state.

    Returns:
        New state at root, or None if already at root.

    """
    if len(state.stack) <= 1:
        return None  # Already at root
    new_stack = state.stack[:1]
    # Path is empty at root (root menu has empty key, excluded from path)
    return replace(state, stack=new_stack, path=())


def pop_item(state: MainState, item_id: str) -> MainState | None:
    """Pop a specific item from the stack by its ID.

    Args:
        state: Current main state.
        item_id: ID of the stack item to remove.

    Returns:
        New state with item removed, or None if item not found.

    """
    new_stack = tuple(item for item in state.stack if item.id != item_id)
    if new_stack == state.stack:
        return None  # Item not found, no change
    new_path = derive_path_from_stack(new_stack)
    return replace(state, stack=new_stack, path=new_path)


def set_page_index(state: MainState, page_index: int) -> MainState | None:
    """Set the page index of the current menu.

    Args:
        state: Current main state.
        page_index: New page index.

    Returns:
        New state with updated page index, or None if top is not a menu.

    """
    if not state.stack:
        return None
    top = state.stack[-1]
    if not isinstance(top, (MenuStackItem, NotificationStackItem)):
        return None  # Can only set page index for menus and notifications
    new_top = replace(top, page_index=page_index)
    new_stack = (*state.stack[:-1], new_top)
    return replace(state, stack=new_stack)

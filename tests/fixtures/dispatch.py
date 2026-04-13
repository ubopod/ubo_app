"""Dispatcher fixture for multi-mode navigation dispatch."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from immutable import Immutable
    from ubo_bindings.store.v1 import StoreServiceStub

    from ubo_app.store.core.types.view_data import MenuItemData


class DispatchMethod(StrEnum):
    """Dispatch mode for menu navigation actions."""

    DIRECT = 'direct'
    GRPC_MENU = 'grpc_menu'
    GRPC_KEYPAD = 'grpc_keypad'


DIRECT = DispatchMethod.DIRECT
GRPC_MENU = DispatchMethod.GRPC_MENU
GRPC_KEYPAD = DispatchMethod.GRPC_KEYPAD


async def _dispatch_via_grpc(
    stub: StoreServiceStub,
    action: Immutable,
) -> None:
    """Serialize a Redux action and send it via gRPC."""
    from typing import Any, cast

    import ubo_bindings.ubo.v1
    from betterproto.casing import snake_case
    from ubo_bindings.store.v1 import DispatchActionRequest

    from ubo_app.rpc.object_to_message import build_message

    proto_msg = cast('Any', build_message(action))
    field_name = snake_case(type(action).__name__)
    wrapped = ubo_bindings.ubo.v1.Action(**{field_name: proto_msg})
    await stub.dispatch_action(DispatchActionRequest(action=wrapped))


def _get_visible_items() -> tuple[MenuItemData | None, ...]:
    """Read visible items from the current view in the store."""
    from ubo_app.store.core.types import (
        HomeViewData,
        MenuViewData,
        NotificationViewData,
    )
    from ubo_app.store.main import store

    state = store._state  # noqa: SLF001
    if state is None:
        msg = 'Store state is None'
        raise RuntimeError(msg)

    current_view = state.main.current_view
    if current_view is None:
        msg = 'Current view is None'
        raise RuntimeError(msg)

    if isinstance(current_view, HomeViewData):
        return current_view.menu_items
    if isinstance(current_view, MenuViewData):
        # Slice to the current page, accounting for headed menus where
        # heading + sub_heading occupy visual slots on page 0.
        from ubo_app.store.core.constants import HEADED_MENU_HEADER_SLOTS, PAGE_SIZE

        items = [i for i in current_view.items if i is not None]
        header_offset = (
            HEADED_MENU_HEADER_SLOTS if current_view.heading is not None else 0
        )
        if current_view.page_index == 0:
            page_start = 0
            page_end = PAGE_SIZE - header_offset
        else:
            page_start = current_view.page_index * PAGE_SIZE - header_offset
            page_end = page_start + PAGE_SIZE
        visible = items[page_start:page_end]
        if current_view.page_index == 0 and header_offset:
            return (None,) * header_offset + tuple(visible)
        return tuple(visible)
    if isinstance(current_view, NotificationViewData):
        # Slice to the current page. Single-page → bottom-aligned,
        # multi-page → top-aligned (matches core handler + GUI renderer).
        from ubo_app.store.core.constants import PAGE_SIZE, compute_total_pages

        real_items = [i for i in current_view.items if i is not None]
        total_pages = compute_total_pages(len(real_items))
        page_start = current_view.page_index * PAGE_SIZE
        page_items = real_items[page_start : page_start + PAGE_SIZE]
        if total_pages <= 1:
            pad = max(PAGE_SIZE - len(page_items), 0)
            return (None,) * pad + tuple(page_items)
        return tuple(page_items)
    msg = f'Unsupported view type: {type(current_view)}'
    raise TypeError(msg)


def _find_item_index(
    items: tuple[MenuItemData | None, ...],
    *,
    label: str | None = None,
    icon: str | None = None,
) -> int | None:
    """Find the index of a matching item in the visible items tuple."""
    for idx, item in enumerate(items):
        if item is None:
            continue
        if label is not None and item.label == label:
            return idx
        if icon is not None and item.icon == icon:
            return idx
    return None


def _get_top_app_button_action_id(index: int) -> str:
    """Return the action_id for a button press on the top stack item.

    For ApplicationStackItem: uses the 'app-button:{app_id}:{index}' convention.
    For PromptStackItem: uses the action_id from the item at position index-1.
    """
    from ubo_app.store.core.types import ApplicationStackItem, PromptStackItem
    from ubo_app.store.main import store

    state = store._state  # noqa: SLF001
    if state is None or not state.main.stack:
        msg = 'Main stack is empty'
        raise RuntimeError(msg)

    top = state.main.stack[-1]
    if isinstance(top, ApplicationStackItem):
        return f'app-button:{top.application_id}:{index}'
    if isinstance(top, PromptStackItem):
        item_index = index - 1
        if item_index < len(top.items):
            action_id = top.items[item_index].action_id
            if action_id:
                return action_id
        msg = f'Prompt item at index {item_index} has no action_id'
        raise ValueError(msg)
    msg = f'Top of stack is not an application or prompt: {type(top)}'
    raise TypeError(msg)


class Dispatcher:
    """Unified dispatcher that routes actions via direct, gRPC menu, or gRPC keypad."""

    def __init__(self: Dispatcher, stub: StoreServiceStub | None) -> None:
        """Initialize with an optional gRPC stub (None if gRPC not needed)."""
        self.stub = stub

    async def choose_by_label(
        self: Dispatcher,
        label: str,
        *,
        via: DispatchMethod,
    ) -> None:
        """Choose a menu item by its label using the specified dispatch method."""
        if via == DispatchMethod.DIRECT:
            from ubo_app.store.core.types import MenuChooseByLabelAction
            from ubo_app.store.main import store

            store.dispatch(MenuChooseByLabelAction(label=label))
        elif via == DispatchMethod.GRPC_MENU:
            from ubo_app.store.core.types import MenuChooseByLabelAction

            await _dispatch_via_grpc(self._stub, MenuChooseByLabelAction(label=label))
        else:
            await self._keypad_choose(label=label)

    async def choose_by_icon(
        self: Dispatcher,
        icon: str,
        *,
        via: DispatchMethod,
    ) -> None:
        """Choose a menu item by its icon using the specified dispatch method."""
        if via == DispatchMethod.DIRECT:
            from ubo_app.store.core.types import MenuChooseByIconAction
            from ubo_app.store.main import store

            store.dispatch(MenuChooseByIconAction(icon=icon))
        elif via == DispatchMethod.GRPC_MENU:
            from ubo_app.store.core.types import MenuChooseByIconAction

            await _dispatch_via_grpc(self._stub, MenuChooseByIconAction(icon=icon))
        else:
            await self._keypad_choose(icon=icon)

    async def go_back(self: Dispatcher, *, via: DispatchMethod) -> None:
        """Go back in the menu using the specified dispatch method."""
        if via == DispatchMethod.DIRECT:
            from ubo_app.store.core.types import MenuGoBackAction
            from ubo_app.store.main import store

            store.dispatch(MenuGoBackAction())
        elif via == DispatchMethod.GRPC_MENU:
            from ubo_app.store.core.types import MenuGoBackAction

            await _dispatch_via_grpc(self._stub, MenuGoBackAction())
        else:
            from ubo_app.store.services.keypad import Key

            await self.send_key(Key.BACK)

    async def app_button(
        self: Dispatcher,
        index: int,
        *,
        via: DispatchMethod,
    ) -> None:
        """Press an application button using the specified dispatch method."""
        if via == DispatchMethod.DIRECT:
            from ubo_app.store.core.types import ExecuteMenuActionAction
            from ubo_app.store.main import store

            action_id = _get_top_app_button_action_id(index)
            store.dispatch(
                ExecuteMenuActionAction(action_id=action_id),
            )
        elif via == DispatchMethod.GRPC_MENU:
            from ubo_app.store.core.types import ExecuteMenuActionAction

            action_id = _get_top_app_button_action_id(index)
            await _dispatch_via_grpc(
                self._stub,
                ExecuteMenuActionAction(action_id=action_id),
            )
        else:
            from ubo_app.store.services.keypad import Key

            key_map = {0: Key.L1, 1: Key.L2, 2: Key.L3}
            await self.send_key(key_map[index])

    @property
    def _stub(self: Dispatcher) -> StoreServiceStub:
        """Return the gRPC stub, raising if not available."""
        if self.stub is None:
            msg = 'gRPC stub not available — dispatcher created without gRPC channel'
            raise RuntimeError(msg)
        return self.stub

    async def _keypad_choose(
        self: Dispatcher,
        *,
        label: str | None = None,
        icon: str | None = None,
    ) -> None:
        """Find target item in current view and send matching keypad press via gRPC."""
        import asyncio

        from ubo_app.store.services.keypad import Key

        max_scroll_attempts = 20
        key_map = {0: Key.L1, 1: Key.L2, 2: Key.L3}

        for attempt in range(max_scroll_attempts):
            items = _get_visible_items()
            idx = _find_item_index(items, label=label, icon=icon)
            if idx is not None:
                await self.send_key(key_map[idx])
                return

            # Item not found on current page — scroll down and retry
            if attempt < max_scroll_attempts - 1:
                await self.send_key(Key.DOWN)
                await asyncio.sleep(0.2)

        match_desc = f'label={label!r}' if label else f'icon={icon!r}'
        msg = (
            f'Item with {match_desc} not found after'
            f' {max_scroll_attempts} scroll attempts'
        )
        raise LookupError(msg)

    async def send_key(self: Dispatcher, key: str) -> None:
        """Send a keypad key press + release action via gRPC.

        The keypad reducer handles some keys on press (L1/L2/L3) and others
        on release (BACK, HOME). Sending both ensures all keys work correctly.
        """
        from ubo_app.store.services.keypad import (
            Key,
            KeypadKeyPressAction,
            KeypadKeyReleaseAction,
        )

        key_enum = Key(key)
        await _dispatch_via_grpc(
            self._stub,
            KeypadKeyPressAction(key=key_enum, pressed_keys=(key_enum,)),
        )
        await _dispatch_via_grpc(
            self._stub,
            KeypadKeyReleaseAction(key=key_enum, pressed_keys=()),
        )


@pytest.fixture
async def dispatcher() -> AsyncGenerator[Dispatcher]:
    """Provide a Dispatcher with access to all three dispatch methods."""
    from grpclib.client import Channel
    from ubo_bindings.store.v1 import StoreServiceStub as StoreServiceStubCls

    from ubo_app.constants import GRPC_LISTEN_PORT

    channel = Channel(host='localhost', port=GRPC_LISTEN_PORT)
    stub = StoreServiceStubCls(channel)
    yield Dispatcher(stub)
    channel.close()
